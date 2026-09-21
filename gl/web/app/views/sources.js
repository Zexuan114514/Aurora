/* Aurora 前端 · 资料源与获取面板（P4.3-n）
 *
 * 三块放在一起，因为它们讲的是同一件事「游戏从哪来」：
 *   - 资料源管理（`renderSources` / `addCustomSource`）
 *   - Steam 扫描导入（`openSteamPanel` / `renderSteamList` / `importSteam`）
 *   - 获取游戏（`openGetPanel` / `renderSites` / 下载目录设置）
 *
 * 与其它视图同规矩：只 import core；面板开合与提示仍由主模块注入
 * （提示 `toast` 由主模块注入），面板开合走 core/panels.js，事件绑定留在主模块。
 */
import { call } from "../core/api.js";
import { $, el, esc } from "../core/dom.js";
import { closeAll, openPanel } from "../core/panels.js";
import { state } from "../core/store.js";

export function createSourcesView(ctx) {
  /* ------------------------------------------------------------ Steam 扫描 */
  function renderSteamList() {
    const rows = state.steam || [];
    if (!rows.length) {
      el.steamList.innerHTML = `<div class="list-empty">没有找到可导入的游戏</div>`;
      return;
    }
    el.steamList.innerHTML = rows.map((row) => `
      <label class="steam-row${row.already ? " off" : ""}">
        <input type="checkbox" class="switch sm" data-exe="${esc(row.exe)}"
               ${state.picked.has(row.exe) ? "checked" : ""} ${row.already ? "disabled" : ""}>
        <div class="steam-body">
          <div class="steam-name">${esc(row.name)}
            ${row.already ? '<span class="src-badge">已在库中</span>' : ""}</div>
          <div class="steam-meta">${esc(row.exe_name)} · ${esc(row.dir)}</div>
        </div>
        <span class="src-badge">${esc(String(row.appid))}</span>
      </label>`).join("");
    updateSteamHint();
  }

  function updateSteamHint() {
    const picked = state.picked.size;
    const active = (state.steam || []).filter((r) => !r.already).length;
    el.steamPickHint.textContent = picked ? `已选 ${picked} 个` : `可导入 ${active} 个`;
    el.steamImport.disabled = !picked;
    el.steamImport.textContent = picked ? `导入选中的 ${picked} 个游戏` : "导入选中的游戏";
  }

  async function openSteamPanel() {
    closeAll();
    state.steam = [];
    state.picked = new Set();
    openPanel(el.steamPanel);
    el.steamSub.textContent = "正在读取 Steam 清单…";
    el.steamList.innerHTML = `<div class="list-empty">正在扫描 Steam 库，第一次可能要十几秒…</div>`;
    el.steamImport.disabled = true;
    try {
      const res = await call("scan_steam");
      if (!res || !res.ok) {
        el.steamSub.textContent = (res && res.error === "no-steam")
          ? "没有在注册表里找到 Steam" : "扫描失败：" + ((res && res.error) || "未知错误");
        el.steamList.innerHTML = `<div class="list-empty">没找到可导入的 Steam 游戏</div>`;
        return;
      }
      state.steam = res.games || [];
      state.steam.forEach((row) => { if (!row.already) state.picked.add(row.exe); });
      el.steamSub.textContent =
        `找到 ${state.steam.length} 个游戏 · ${(res.libraries || []).length} 个库目录`;
      renderSteamList();
    } catch (e) {
      el.steamSub.textContent = "扫描失败：" + e.message;
      el.steamList.innerHTML = `<div class="list-empty">扫描失败</div>`;
    }
  }

  async function importSteam() {
    const items = (state.steam || [])
      .filter((row) => state.picked.has(row.exe))
      .map((row) => ({ exe: row.exe, appid: row.appid, name: row.name }));
    if (!items.length) return;
    state.batch = { kind: "steam", done: 0, total: items.length };
    el.steamImport.disabled = true;
    el.steamImport.textContent = `导入中 0/${items.length}`;
    const res = await call("import_steam_games", items);
    if (!res || !res.ok) {
      state.batch = null;
      updateSteamHint();
      ctx.toast("导入失败：" + ((res && res.error) || "未知错误"));
    }
  }

  /* ------------------------------------------------------------ 获取游戏 */
  function renderSites() {
    const sites = state.sites || [];
    if (!sites.length) {
      el.getSites.innerHTML = '<span class="get-hint">还没有资源站，点右边「＋ 添加站点」加一个</span>';
      return;
    }
    el.getSites.innerHTML = sites.map((row) => `
      <span class="site-chip">
        <button class="link-chip" data-site="${esc(row.id)}"
                title="${esc(row.url)}">${esc(row.name)}</button>
        <button class="site-del" data-del="${esc(row.id)}" title="删除这个站点">×</button>
      </span>`).join("");
  }

  async function refreshSites() {
    try {
      const res = await call("list_sites");
      state.sites = (res && res.sites) || [];
    } catch (_) {
      state.sites = state.sites || [];
    }
    renderSites();
  }

  async function openSite(siteId) {
    const res = await call("open_site", siteId, el.getQuery.value.trim());
    if (!res || !res.ok) ctx.toast("打不开这个站点：" + ((res && res.error) || ""));
  }

  async function addSite() {
    const name = $("getSiteName").value.trim();
    const url = $("getSiteUrl").value.trim();
    if (!name || !url) { ctx.toast("名称和地址都要填"); return; }
    const res = await call("add_site", name, url);
    if (!res || !res.ok) {
      ctx.toast(res && res.error === "bad-url"
        ? "地址要以 http:// 或 https:// 开头" : "添加失败");
      return;
    }
    state.sites = res.sites || [];
    renderSites();
    el.getSiteForm.hidden = true;
    ctx.toast(`已添加资源站：${name}`);
  }

  async function refreshDownloadSettings() {
    try {
      const s = await call("get_download_settings");
      if (!s || !s.ok) return;
      el.getDir.textContent = s.dir || "—";
      el.getWatch.checked = !!s.watch;
      el.getExtract.checked = !!s.extract;
      el.getDirHint.textContent = s.extractor
        ? `· 解压工具：${s.extractor} 已就绪`
        : "· 没找到解压工具（.zip 内置；.rar/.7z 需装 7-Zip 或 WinRAR）";
    } catch (_) { /* 面板还没准备好就忽略 */ }
  }

  async function openGetPanel() {
    closeAll();
    openPanel(el.getPanel);
    await refreshSites();
    await refreshDownloadSettings();
  }

  /* ------------------------------------------------------------ 资料源管理 */
  function renderSources() {
    const list = state.sources || [];
    if (!list.length) {
      el.sourceList.innerHTML = `<div class="list-empty">还没有启用任何资料源</div>`;
      return;
    }
    el.sourceList.innerHTML = list.map((s, index) => `
      <div class="src-row${s.enabled ? "" : " off"}" data-id="${esc(s.id)}">
        <div class="src-arrow-group" style="display:flex;flex-direction:column;gap:2px">
          <button class="src-arrow" data-move="-1" ${index === 0 ? "disabled" : ""}>▲</button>
          <button class="src-arrow" data-move="1"
                  ${index === list.length - 1 ? "disabled" : ""}>▼</button>
        </div>
        <div class="src-body">
          <div class="src-name">
            ${esc(s.name)}
            <span class="src-badge${s.kind === "link" ? " link" : ""}">
              ${s.kind === "link" ? "跳转" : "API"}${s.builtin ? "" : " · 自定义"}</span>
          </div>
          <div class="src-meta">${esc(s.search_url || s.homepage || "")}</div>
        </div>
        <button class="src-act" data-act="test">测试</button>
        ${s.builtin ? "" : '<button class="src-act danger" data-act="remove">删除</button>'}
        <input type="checkbox" class="switch" data-act="toggle" ${s.enabled ? "checked" : ""}>
      </div>`).join("");
  }

  async function refreshSources() {
    const rows = await call("list_sources");
    state.sources = rows || [];
    renderSources();
    applySourcesHint();
  }

  function applySourcesHint() {
    const enabled = (state.sources || []).filter((s) => s.enabled).length;
    $("sourcesHint").textContent = `${enabled} 个启用`;
  }

  function syncSourceForm() {
    $("srcApiFields").hidden = $("srcKind").value !== "api";
  }

  async function addCustomSource() {
    const name = $("srcName").value.trim();
    const url = $("srcUrl").value.trim();
    if (!name || !url) { ctx.toast("名称和搜索地址都要填"); return; }
    const cfg = { name, kind: $("srcKind").value, search_url: url };
    if (cfg.kind === "api") {
      cfg.results_path = $("srcResults").value.trim() || "data";
      const raw = $("srcFields").value.trim();
      if (raw) {
        try {
          cfg.fields = JSON.parse(raw);
        } catch (e) {
          ctx.toast("字段映射不是合法的 JSON");
          return;
        }
      } else {
        cfg.fields = {};
      }
    }
    const res = await call("add_custom_source", cfg);
    state.sources = res.sources || state.sources;
    renderSources();
    applySourcesHint();
    el.sourceForm.hidden = true;
    ctx.toast("已添加：" + name);
    const test = await call("test_source", res.source.id);
    if (test.kind === "link") ctx.toast(`${name} 已添加（跳转型，候选面板里可直接点）`);
    else if (test.ok) ctx.toast(`${name} 可用：${test.count} 个结果 · ${(test.sample || []).join(" / ")}`);
    else ctx.toast(`${name} 没有返回结果，请检查地址与字段映射`);
  }

  /** 打开资料源管理面板（先全关，再拉一次列表）。 */
  async function openSourcePanel() {
    closeAll();
    await refreshSources();
    openPanel(el.sourcePanel);
  }

  return {
    renderSteamList, updateSteamHint, openSteamPanel, importSteam,
    renderSites, refreshSites, openSite, addSite, refreshDownloadSettings, openGetPanel,
    renderSources, refreshSources, applySourcesHint, syncSourceForm, addCustomSource,
    openSourcePanel,
  };
}
