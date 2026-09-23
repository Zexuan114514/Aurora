"""本地静态资源服务（P5，ADR-0005）：`/` 服务随包前端，`/assets/` 映射数据目录。

为什么自建：用户素材（背景图 / 自定义封面 / 自定义图标）原先要复制进 `gl/web/` 才能被页面读到，
一份数据两个位置；单文件 exe 下 `web/` 还是临时解压目录，写入副本本身就不稳。
现在只服务一次：原图留在 `data/` 下，由这里按 `/assets/<mount>/<文件名>` 暴露。

约束（ADR-0005 决定 2）：
  * 只允许 `GET` / `HEAD`，其它方法 405
  * 只绑定 `127.0.0.1`，端口取空闲端口
  * 路径规范化后必须落在白名单目录内；`..` / 绝对路径 / 目录本身一律 403 / 404
  * 前端文件用 `no-store`（入口本来就带 `?v=`），用户素材用 `no-cache`（换了图立刻生效）
"""
from __future__ import annotations

import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

__all__ = ["start", "AssetServer", "ASSET_PREFIX"]

ASSET_PREFIX = "/assets/"
_NO_STORE_SUFFIXES = {".html", ".css", ".js", ".mjs", ".svg", ".json"}
#: v2 前端是 Vite 产物：bundle/ 下的文件名自带内容哈希，可以长缓存。
#: 入口 index.html 仍然 no-store（它不带哈希，必须每次校验）。
_IMMUTABLE_PREFIX = "/v2/bundle/"


def _safe_join(root: Path, rel: str) -> Path | None:
    """把 URL 里的相对路径安全地拼到 root 下；越界或不是普通文件都返回 None。"""
    rel = unquote(rel or "")
    if "\x00" in rel:
        return None
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(part == ".." for part in parts):
        return None
    try:
        root_resolved = root.resolve()
        candidate = root_resolved.joinpath(*parts).resolve()
    except OSError:
        return None
    if candidate != root_resolved and root_resolved not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


class _Handler(BaseHTTPRequestHandler):
    server_version = "AuroraAssets/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:      # noqa: A003
        pass

    def log_error(self, fmt: str, *args) -> None:        # noqa: A003
        pass

    def do_GET(self) -> None:                            # noqa: N802
        self._serve(with_body=True)

    def do_HEAD(self) -> None:                           # noqa: N802
        self._serve(with_body=False)

    def _method_not_allowed(self) -> None:
        """只允许读：其余方法统一 405（并告诉对方允许什么）。"""
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = _method_not_allowed                        # noqa: N815
    do_PUT = _method_not_allowed                         # noqa: N815
    do_DELETE = _method_not_allowed                      # noqa: N815
    do_PATCH = _method_not_allowed                       # noqa: N815
    do_OPTIONS = _method_not_allowed                     # noqa: N815

    def _deny(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve(self, with_body: bool) -> None:
        path = urlparse(self.path).path
        target: Path | None
        if path.startswith(ASSET_PREFIX):
            rest = path[len(ASSET_PREFIX):]
            mount, _, rel = rest.partition("/")
            root = self.server.assets.get(mount)
            if root is None:
                self._deny(403)          # 未挂载的目录名：不告诉对方哪里存在什么
                return
            target = _safe_join(root, rel)
        else:
            rel = path.lstrip("/") or "index.html"
            target = _safe_join(self.server.web_dir, rel)
        if target is None:
            self._deny(404)
            return

        try:
            data = target.read_bytes()
        except OSError:
            self._deny(404)
            return

        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if path.startswith(_IMMUTABLE_PREFIX):
            cache = "public, max-age=31536000, immutable"
        else:
            cache = ("no-store" if target.suffix.lower() in _NO_STORE_SUFFIXES else "no-cache")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if with_body:
            self.wfile.write(data)


class AssetServer(ThreadingHTTPServer):
    """绑定 127.0.0.1:0（让系统挑空闲端口）的静态服务。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, web_dir: Path, assets: dict[str, Path]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.web_dir = Path(web_dir)
        self.assets = {name: Path(path) for name, path in assets.items()}

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass
        try:
            self.server_close()
        except Exception:
            pass


def start(web_dir: Path, assets: dict[str, Path]) -> AssetServer:
    """起服务并返回句柄（后台守护线程跑 `serve_forever`）。"""
    server = AssetServer(web_dir, assets)
    threading.Thread(target=server.serve_forever, name="aurora-webserver",
                     daemon=True).start()
    return server
