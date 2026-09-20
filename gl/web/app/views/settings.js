/* Aurora 前端 · 设置视图（P4.3-c）
 *
 * 设置页的开关与分页导航。渲染/刷新用的主模块函数由 `createSettingsView(ctx)`
 * 注入 —— 视图只依赖 core，不反向 import 主模块。
 */
import { call } from "../core/api.js";
import { $, el } from "../core/dom.js";
import { state } from "../core/store.js";

export function createSettingsView(ctx) {
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
      ctx.closeAll();
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
        ctx.applySettingsToUi();
      } catch (_) { /* 离线也要能开设置 */ }
      ctx.refreshNetworkPane();
      ctx.refreshLocalePane();
      ctx.refreshVntext();
      ctx.renderGlossary();
    }


  return {setSettingsTab, openSettings, closeSettings, refreshSettingsPanes
  };
}
