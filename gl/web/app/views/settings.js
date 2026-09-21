/* Aurora 前端 · 设置视图（P4.3-c 开刀，P4.3-t 收口）
 *
 * 设置页整块都在这里：页签导航、开合、各栏的渲染（关于 / 网络 / 转区 / 外观 / 翻译），
 * 还有主题与配色的应用、设置的落盘（`saveSetting`）与所有设置项的事件绑定。
 *
 * 视图只依赖 core；主模块的函数（`render` / `refreshLibrary`）与其它视图的入口
 * （资料源面板、批量任务、背景的 Ken Burns、环的布局重排）由 `createSettingsView(ctx)`
 * 注入 —— 一律箭头延迟取值，避开 P4.3-c 踩过的 TDZ 坑。
 */
import { call } from "../core/api.js";
import { $, el, esc } from "../core/dom.js";
import { closeAll } from "../core/panels.js";
import { state } from "../core/store.js";

export const LE_URL = "https://github.com/xupefei/Locale-Emulator/releases";

const PALETTES = [
  { key: "aurora", name: "极光蓝", accent: "#0A84FF", accent2: "#4FA9FF" },
  { key: "lime", name: "薄荷青", accent: "#26C6A8", accent2: "#6FE0C8" },
  { key: "sakura", name: "樱花粉", accent: "#FF5C8A", accent2: "#FF9AB6" },
  { key: "amber", name: "琥珀橙", accent: "#FF9F0A", accent2: "#FFC46B" },
];

const lightQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

export function createSettingsView(ctx) {
  /* ------------------------------------------------------------ 主题与配色 */
  function effectiveTheme() {
    const mode = state.settings.theme_mode || "dark";
    if (mode === "auto") return lightQuery && lightQuery.matches ? "light" : "dark";
    return mode === "light" ? "light" : "dark";
  }

  /* 主题只负责 data-theme / data-palette 与窗口外框；强调色跟着设置走 */
  function applyTheme() {
    const theme = effectiveTheme();
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.palette = state.settings.palette || "aurora";
    try { call("apply_window_theme", theme === "light").catch(() => {}); } catch (_) { /* 离线 */ }
  }

  function renderPaletteRow() {
    const active = state.settings.palette || "aurora";
    $("setPalettes").innerHTML = PALETTES.map((p) => `
      <button type="button" class="palette-chip${active === p.key ? " on" : ""}"
              data-palette="${p.key}" title="${p.name}">
        <i style="background:${p.accent}"></i><span>${p.name}</span>
      </button>`).join("")
      + `<span class="palette-custom${active === "custom" ? " on" : ""}">自定义</span>`;
  }

  function bindTheme() {
    $("setTheme").onchange = async (e) => {
      await saveSetting("theme_mode", e.target.value);
      applyTheme();
      ctx.toast(e.target.value === "light" ? "已切换到浅色主题"
        : (e.target.value === "auto" ? "主题跟随系统" : "已切换到深色主题"));
    };
    $("setHallLayout").onchange = async (e) => {
      await saveSetting("hall_layout", e.target.value);
      ctx.ringApplyLayout();
      ctx.toast(e.target.value === "flat" ? "主页布局：平铺横滑（NS 大厅）"
                                           : "主页布局：环形队列");
    };
    $("setPalettes").onclick = async (e) => {
      const chip = e.target.closest("[data-palette]");
      if (!chip) return;
      const preset = PALETTES.find((p) => p.key === chip.dataset.palette);
      if (!preset) return;
      state.settings.palette = preset.key;
      state.settings.accent = preset.accent;
      applySettingsToUi();
      renderPaletteRow();
      await call("set_setting", "palette", preset.key);
      await call("set_setting", "accent", preset.accent);
      ctx.toast(`已应用配色：${preset.name}`);
    };
    if (lightQuery) {
      const onChange = () => { if ((state.settings.theme_mode || "dark") === "auto") applyTheme(); };
      if (lightQuery.addEventListener) lightQuery.addEventListener("change", onChange);
      else if (lightQuery.addListener) lightQuery.addListener(onChange);
    }
  }

  /* ------------------------------------------------------------ 设置：网络 */
  async function refreshNetworkPane() {
    try {
      const net = await call("get_network_status");
      if (!net || !net.ok) return;
      $("setProxyMode").value = net.mode || "auto";
      $("setProxyUrl").value = net.url || "";
      $("setProxyFallback").checked = net.fallback !== false;
      el.netStatus.textContent = net.proxy
        ? `当前生效：${net.proxy}（来源：${net.source}）`
        : `当前生效：直连（来源：${net.source || "系统设置"}）`;
    } catch (err) {
      el.netStatus.textContent = "读取代理设置失败：" + err.message;
    }
  }

  function renderNetResults(rows) {
    el.netResults.innerHTML = (rows || []).map((row) => `
      <div class="net-line${row.ok ? " ok" : ""}">
        <i class="dot"></i><span class="name">${esc(row.name)}</span>
        <span class="detail">${esc(row.detail || "")}</span>
      </div>`).join("");
  }

  async function testNetwork() {
    const btn = $("netTest");
    btn.disabled = true;
    el.netResults.innerHTML = '<div class="net-line"><i class="dot"></i><span class="name">正在测试…</span></div>';
    try {
      const res = await call("test_network");
      renderNetResults((res && res.results) || []);
      if (res && res.proxy) {
        el.netStatus.textContent = `当前生效：${res.proxy}（来源：${res.source}）`;
      }
    } catch (err) {
      renderNetResults([{ name: "测试失败", ok: false, detail: err.message }]);
    } finally {
      btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------ 设置：转区启动 */
  async function refreshLocalePane() {
    try {
      const st = await call("get_locale_status");
      state.locale = st || {};
      const proc = (st && st.proc) || "";
      $("setLePath").value = proc;
      $("setLocaleDefault").checked = !!(st && st.default_enabled);
      if (st && st.available) {
        el.leStatus.textContent = `已检测到 Locale Emulator：${proc}`;
      } else if (proc) {
        el.leStatus.textContent = "指定的 LEProc.exe 不可用（缺少运行时文件），请重新选择。";
      } else {
        el.leStatus.textContent = "未检测到 Locale Emulator。装好后点「重新检测」，或手动指定 LEProc.exe。";
      }
      const profiles = (st && st.profiles) || [];
      el.leProfiles.innerHTML = profiles.length
        ? profiles.map((row) => `<span class="src-badge">${esc(row.name || row.guid)}</span>`).join("")
        : (st && st.available
            ? '<span class="hint">没有读到 LEConfig.xml 里的全局配置，转区时会用 LE 的默认配置。</span>'
            : "");
    } catch (err) {
      el.leStatus.textContent = "检测失败：" + err.message;
    }
  }

  /* ------------------------------------------------------------ 外观回填与保存 */
  function applySettingsToUi() {
    const s = state.settings;
    document.documentElement.style.setProperty("--blur", (s.blur ?? 30) + "px");
    document.documentElement.style.setProperty("--sat", (s.saturation ?? 190) + "%");
    document.documentElement.style.setProperty("--scrim", String(s.scrim ?? 42) / 100);
    if (s.accent) document.documentElement.style.setProperty("--accent", s.accent);
    applyTheme();

    $("setBlur").value = s.blur ?? 30;
    $("setScrim").value = s.scrim ?? 42;
    $("setAccent").value = s.accent || "#0A84FF";
    $("setSat").value = s.saturation ?? 190;
    $("setKen").checked = !!s.ken_burns;
    $("setLang").value = s.lang || "schinese";
    $("setMerge").checked = s.sources ? s.sources.merge_images !== false : true;
    $("setTray").checked = !!s.close_to_tray;
    $("setTransEnabled").checked = s.translate_enabled !== false;
    $("setTransProvider").value = s.translate_provider || "auto";
    $("setTransBase").value = s.translate_base_url || "";
    $("setTransKey").value = s.translate_api_key || "";
    $("setTransModel").value = s.translate_model || "";
    $("setShowOriginal").checked = !!s.show_original;
    $("setTheme").value = s.theme_mode || "dark";
    $("setHallLayout").value = s.hall_layout === "flat" ? "flat" : "ring";
    ctx.ringApplyLayout();
    renderPaletteRow();
    $("setVnEngine").value = s.vntext_engine || "auto";
    $("setBlurVal").textContent = (s.blur ?? 30) + "px";
    $("setScrimVal").textContent = (s.scrim ?? 42) + "%";
    $("setSatVal").textContent = (s.saturation ?? 190) + "%";
  }

  async function saveSetting(key, value) {
    state.settings[key] = value;
    applySettingsToUi();
    if (key === "ken_burns") ctx.applyKenBurns(value);
    await call("set_setting", key, value);
  }

  /* ------------------------------------------------------------ 页签导航与开合 */
  function setSettingsTab(name) {
    state.settingsTab = name || "look";
    for (const tab of el.setNav.querySelectorAll(".set-tab")) {
      tab.classList.toggle("on", tab.dataset.pane === state.settingsTab);
    }
    for (const pane of el.settingsView.querySelectorAll(".set-pane")) {
      pane.classList.toggle("on", pane.dataset.pane === state.settingsTab);
    }
  }

  async function openSettings(tab) {
    state.settingsOpen = true;
    closeAll();
    ctx.render();
    setSettingsTab(tab || state.settingsTab);
    await refreshSettingsPanes();
  }

  function closeSettings() {
    state.settingsOpen = false;
    el.settingsView.hidden = true;
    ctx.render();
  }

  async function refreshSettingsPanes() {
    $("aboutVersion").textContent = state.version || "—";
    try {
      const info = await call("bootstrap");
      $("aboutDataDir").textContent = info.data_dir || "—";
      state.settings = info.settings || state.settings;
      state.version = info.version || state.version;
      $("aboutVersion").textContent = state.version || "—";
      applySettingsToUi();
    } catch (_) { /* 离线也要能开设置 */ }
    refreshNetworkPane();
    refreshLocalePane();
    ctx.refreshVntext();
    ctx.renderGlossary();
  }

  /* ------------------------------------------------------------ 设置项的事件绑定 */
  function bind() {
    // 齿轮是开关：点开、再点一次（或用「← 返回」）都能退出设置
    $("btnSettings").onclick = () => (state.settingsOpen ? closeSettings() : openSettings());
    $("setBack").onclick = closeSettings;
    el.setNav.addEventListener("click", (e) => {
      const tab = e.target.closest(".set-tab");
      if (tab) setSettingsTab(tab.dataset.pane);
    });

    // 设置 → 网络
    $("setProxyMode").onchange = async (e) => {
      await call("set_proxy_option", "proxy_mode", e.target.value);
      ctx.toast(e.target.value === "direct" ? "已切换为直连" : "代理设置已保存");
      refreshNetworkPane();
    };
    $("setProxyUrl").onchange = async (e) => {
      const res = await call("set_proxy_option", "proxy_url", e.target.value.trim());
      if (res && res.ok === false) ctx.toast("代理地址无效：" + (res.error || ""));
      refreshNetworkPane();
    };
    $("setProxyFallback").onchange = async (e) => {
      await call("set_proxy_option", "proxy_fallback", e.target.checked);
    };
    $("netTest").onclick = testNetwork;

    // 设置 → 转区启动
    $("setLocaleDefault").onchange = async (e) => {
      await call("set_locale_option", "locale_default", e.target.checked);
      ctx.toast(e.target.checked ? "新导入的游戏默认开启转区" : "已关闭默认转区");
    };
    $("setLePick").onclick = async () => {
      const res = await call("pick_locale_proc");
      if (!res || res.cancelled) return;
      if (!res.ok) { ctx.toast("这个路径不可用：" + ((res && res.error) || "")); return; }
      await refreshLocalePane();
      ctx.toast("已设置 Locale Emulator 路径");
    };
    $("setLeRefresh").onclick = refreshLocalePane;
    $("setLeDownload").onclick = () => call("open_url", LE_URL);
    $("btnOpenData").onclick = () => call("open_data_dir");

    // 设置 → 外观
    $("setBlur").oninput = (e) => {
      state.settings.blur = Number(e.target.value);
      applySettingsToUi();
    };
    $("setBlur").onchange = (e) => saveSetting("blur", Number(e.target.value));
    $("setScrim").oninput = (e) => {
      state.settings.scrim = Number(e.target.value);
      applySettingsToUi();
    };
    $("setScrim").onchange = (e) => saveSetting("scrim", Number(e.target.value));
    $("setAccent").oninput = (e) => {
      state.settings.accent = e.target.value;
      applySettingsToUi();
    };
    $("setAccent").onchange = async (e) => {
      await saveSetting("accent", e.target.value);
      await saveSetting("palette", "custom");     // 手选颜色 = 自定义配色
      renderPaletteRow();
    };
    $("setSat").oninput = (e) => {
      state.settings.saturation = Number(e.target.value);
      applySettingsToUi();
    };
    $("setSat").onchange = (e) => saveSetting("saturation", Number(e.target.value));
    $("setKen").onchange = (e) => saveSetting("ken_burns", e.target.checked);
    $("setLang").onchange = (e) => saveSetting("lang", e.target.value);
    $("setMerge").onchange = async (e) => {
      const res = await call("set_merge_sources", e.target.checked);
      if (state.settings.sources) state.settings.sources.merge_images = res.merge_images;
      ctx.toast(e.target.checked ? "已开启多源补图" : "已关闭多源补图");
    };
    $("setTray").onchange = async (e) => {
      await saveSetting("close_to_tray", e.target.checked);
      ctx.toast(e.target.checked
        ? "已开启：关窗口时缩到托盘，游戏继续跑"
        : "已关闭：关窗口即退出");
    };
    bindTheme();

    // 设置 → 简介翻译
    $("setTransEnabled").onchange = (e) => saveSetting("translate_enabled", e.target.checked);
    $("setTransProvider").onchange = (e) => saveSetting("translate_provider", e.target.value);
    $("setTransBase").onchange = (e) => saveSetting("translate_base_url", e.target.value.trim());
    $("setTransKey").onchange = (e) => saveSetting("translate_api_key", e.target.value.trim());
    $("setTransModel").onchange = (e) => saveSetting("translate_model", e.target.value.trim());
    $("setShowOriginal").onchange = async (e) => {
      await saveSetting("show_original", e.target.checked);
      ctx.render();
    };
    $("transTest").onclick = async () => {
      const status = $("transStatus");
      status.textContent = "测试中…";
      const res = await call("test_translation", {
        translate_provider: $("setTransProvider").value,
        translate_base_url: $("setTransBase").value.trim(),
        translate_api_key: $("setTransKey").value.trim(),
        translate_model: $("setTransModel").value.trim(),
      });
      if (res && res.ok) {
        status.textContent = `可用（${res.provider}）：${res.text}`;
        ctx.toast("翻译接口可用");
      } else {
        status.textContent = "不可用：" + ((res && res.error) || "未知错误");
        ctx.toast("翻译接口不可用");
      }
    };
    $("btnShowOriginal").onclick = async () => {
      await saveSetting("show_original", !state.settings.show_original);
      ctx.render();
    };

    // 设置 → 资料源 / Steam / 批量
    $("btnSources").onclick = () => ctx.openSourcePanel();
    $("btnSteamScan").onclick = () => ctx.openSteamPanel();
    $("btnRefreshAll").onclick = () => ctx.startRefreshAll();
    $("btnTranslateAll").onclick = () => ctx.startTranslateAll();

    // 设置 → 备份 / 恢复
    $("btnExport").onclick = async () => {
      const res = await call("export_library");
      if (!res || res.cancelled) return;
      if (!res.ok) { ctx.toast("导出失败：" + ((res && res.error) || "")); return; }
      ctx.toast(`已导出 ${res.games} 个游戏到 ${res.path.split("\\").pop()}`, 4200);
    };
    $("btnImportLib").onclick = async () => {
      const res = await call("import_library");
      if (!res || res.cancelled) return;
      if (!res.ok) {
        ctx.toast(res && res.error === "bad-file"
          ? "这个文件不是 Aurora 导出的游戏库" : "导入失败");
        return;
      }
      await ctx.refreshLibrary();
      ctx.render();
      ctx.toast(`导入完成：新增 ${res.added} 个，跳过 ${res.skipped} 个`);
    };
  }

  return {
    setSettingsTab, openSettings, closeSettings, refreshSettingsPanes,
    applySettingsToUi, saveSetting, renderPaletteRow, applyTheme,
    refreshNetworkPane, refreshLocalePane, testNetwork, bind,
  };
}
