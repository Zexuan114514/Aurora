"""金样本回归：P1 搬迁前后，domain 层的行为必须逐字一致。

金样本由 `tools/checks` 之外的一次性脚本在**搬迁前**从现有实现捕获
（见各 golden 文件的 `captured_from`），测试同时校验：
  1. `aurora.domain.*` 的返回值与快照一致；
  2. 老入口（`gl.vntext` / `gl.detect` / `gl.process`）仍然指向同一实现（转发 shim 没走偏）。
"""
from __future__ import annotations

import dataclasses
import importlib
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
GOLDEN_FILES = ("text_rules", "engine_rules", "matching", "session_rules")
#: 哪些 golden 的 shim 必须与 domain 指向同一个函数对象
IDENTITY_SHIMS = {"text_rules": "gl.vntext", "engine_rules": "gl.vntext", "matching": "gl.detect"}


def load_golden(name: str) -> dict:
    return json.loads((GOLDEN_DIR / f"{name}.golden.json").read_text(encoding="utf-8"))


def decode(value):
    """把 golden 里的占位符还原成真实对象（Path / set / dataclass）。"""
    if isinstance(value, dict):
        keys = set(value)
        if keys == {"__path__"}:
            return pathlib.Path(value["__path__"])
        if keys == {"__set__"}:
            return {decode(item) for item in value["__set__"]}
        if keys == {"__dataclass__", "fields"}:
            contracts = importlib.import_module("aurora.domain.contracts")
            cls = getattr(contracts, value["__dataclass__"])
            return cls(**{k: decode(v) for k, v in value["fields"].items()})
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(item) for item in value]
    return value


def encode(value):
    """与捕获脚本同一套归一化，保证比较口径一致。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {"__dataclass__": type(value).__name__,
                "fields": {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value, pathlib.Path):
        return {"__path__": str(value)}
    if isinstance(value, (set, frozenset)):
        return {"__set__": [encode(v) for v in sorted(value, key=str)]}
    if isinstance(value, tuple):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    return value


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_domain_matches_golden(name: str) -> None:
    payload = load_golden(name)
    module = importlib.import_module(payload["module"])
    failures = []
    for case in payload["cases"]:
        fn = getattr(module, case["fn"])
        args = decode(case.get("args", []))
        kwargs = decode(case.get("kwargs", {}))
        actual = encode(fn(*args, **kwargs))
        if actual != case["expected"]:
            failures.append(f"{case['id']}: 期望 {case['expected']!r}，实际 {actual!r}")
    assert not failures, f"{name} 有 {len(failures)} 个用例与金样本不一致：\n" + "\n".join(failures)


@pytest.mark.parametrize("name", sorted(IDENTITY_SHIMS))
def test_shim_reexports_domain_appendix(name: str) -> None:
    """老入口转发到 domain 的必须是同一个函数对象，避免「两份实现各自演化」。

    默认按文件级 shim 检查，用例可以用 `shim` 字段覆盖（例如 matching 里来自
    `gl/sources/manager.py` 的打分判定，转发点是 manager 而不是 detect）。
    """
    payload = load_golden(name)
    module = importlib.import_module(payload["module"])
    checked: dict[str, set[str]] = {}
    mismatched, missing = [], []
    for case in payload["cases"]:
        fname = case["fn"]
        shim_name = case.get("shim") or IDENTITY_SHIMS[name]
        if not hasattr(module, fname) or not shim_name:
            continue
        shim = importlib.import_module(shim_name)
        checked.setdefault(shim_name, set()).add(fname)
        if not hasattr(shim, fname):
            missing.append(f"{shim_name}.{fname}")
            continue
        if getattr(shim, fname) is not getattr(module, fname):
            mismatched.append(f"{shim_name}.{fname}")
    assert not missing and not mismatched, (
        f"转发不完整：缺失 {sorted(set(missing))}，不是同一对象 {sorted(set(mismatched))}")
    assert checked, f"{name} 没有可校验的转发点"


def test_session_rules_wired_into_process_and_api() -> None:
    """会话公式只应有一份实现：process / api 都必须引用 domain 模块。"""
    domain = importlib.import_module("aurora.domain.session_rules")
    processor = importlib.import_module("gl.process")
    api = importlib.import_module("gl.api")
    assert processor.session_rules is domain
    assert api.session_rules is domain
    source = (ROOT / "gl" / "api.py").read_text(encoding="utf-8")
    assert "min(beat, now)" not in source, "api.py 里不该再留内联的补记公式"
