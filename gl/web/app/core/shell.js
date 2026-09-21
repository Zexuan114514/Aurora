/* Aurora 前端 · 全局外壳（P4.3-x）
 *
 * 不属于任何一块界面的那几件事：
 *   - 点空白处收起工具条菜单（更多 / 排序 / 末尾方块 / 作用域）
 *   - 全局快捷键：Esc 逐层退出、F5 与 Ctrl+R 拦掉、Ctrl+F 搜索、其余交给大厅（← → / Home / End / Enter）
 *   - 右键菜单：输入框里保留系统菜单，其它地方禁用
 *   - 拖放提示层：真正的导入由后端（main.py 注册的 drop 监听）完成，这里只管提示与阻止默认行为
 *
 * ctx = { closeSettings, setView, closeGame, handleRingKey }
 */
import { el } from "./dom.js";
import { closeAll } from "./panels.js";
import { state } from "./store.js";

export function createShell(ctx) {
  function bind() {
    // 点空白处收起菜单
    document.addEventListener("click", (e) => {
      if (!e.target.closest("#moreMenu, #btnMore")) el.moreMenu.hidden = true;
      if (!e.target.closest("#sortMenu, #btnSort")) el.sortMenu.hidden = true;
      if (!e.target.closest("#addMenu, .gi-add")) el.addMenu.hidden = true;
      if (!e.target.closest("#scopeMenu, #scopePill")) el.scopeMenu.hidden = true;
    });

    document.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.target?.isContentEditable;
      if (e.key === "Escape") {
        const anyOpen = [el.bgPanel, el.detailPanel, el.matchPanel, el.sourcePanel,
                         el.coverPanel, el.steamPanel, el.localePanel, el.vntextPanel,
                         el.getPanel]
          .some((p) => p.classList.contains("open"));
        const menuOpen = !el.moreMenu.hidden || !el.sortMenu.hidden || !el.addMenu.hidden
          || !el.scopeMenu.hidden;
        if (anyOpen || menuOpen) { closeAll(); return; }
        if (state.settingsOpen) { ctx.closeSettings(); return; }
        if (state.view === "categories") { ctx.setView("home"); return; }
        if (state.page === "game") { ctx.closeGame(); return; }
      }
      if (e.key === "F5" || (e.ctrlKey && e.key.toLowerCase() === "r")) e.preventDefault();
      // 设置页是独立界面：除 Esc（上面已处理）外的快捷键一律不抢，
      // 免得滚动/切页签时顺带把大厅的焦点、背景甚至游戏启动状态也改了
      if (state.settingsOpen || state.view === "categories") return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        const box = state.view === "categories" ? el.catQuery : el.search;
        box.focus();
        box.select();
        return;
      }
      if (typing || !el.modal.hidden) return;
      // 大厅快捷键（← → / Home / End / Enter）在 ./app/views/hall.js
      ctx.handleRingKey(e);
    });

    document.addEventListener("contextmenu", (e) => {
      if (!e.target.closest("input,textarea,[contenteditable]")) e.preventDefault();
    });

    // 拖放：真正的导入由后端完成，这里只负责提示层与阻止浏览器打开文件
    const hasFiles = (e) => {
      const types = (e.dataTransfer && e.dataTransfer.types) || [];
      return Array.prototype.indexOf.call(types, "Files") >= 0;
    };
    let dragDepth = 0;
    document.addEventListener("dragenter", (e) => {
      if (!hasFiles(e)) return;
      dragDepth += 1;
      el.dropHint.hidden = false;
    });
    document.addEventListener("dragover", (e) => {
      if (hasFiles(e)) e.preventDefault();
    });
    document.addEventListener("dragleave", (e) => {
      if (!hasFiles(e)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) el.dropHint.hidden = true;
    });
    document.addEventListener("drop", (e) => {
      dragDepth = 0;
      el.dropHint.hidden = true;
      e.preventDefault();
    });
  }

  return { bind };
}
