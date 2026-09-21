/* Aurora 前端 · 面板管路（P4.3-o）
 *
 * 面板的「开 / 关 / 全关」从主模块搬到这里，因为三边都要用：
 *   - 主模块的事件绑定（各个关闭按钮、ESC）
 *   - `views/game.js`（背景 / 详情 / 换封面 / 候选面板）
 *   - `views/sources.js`（资料源 / Steam / 获取游戏）
 *   - `views/settings.js`（开设置页时先全关）
 *
 * 面板本身仍是 index.html 里带 `.open` 类的浮层，这里只做类名与菜单开关，
 * 不碰任何内容渲染（渲染各自留在所属视图）。
 */
import { el } from "./dom.js";

export const openPanel = (node) => node.classList.add("open");

export const closePanel = (node) => node.classList.remove("open");

/** 关掉所有浮层与工具条菜单（切页、开新面板、按 Esc 时都走这里）。 */
export const closeAll = () => {
  closePanel(el.bgPanel); closePanel(el.detailPanel); closePanel(el.matchPanel);
  closePanel(el.sourcePanel);
  closePanel(el.coverPanel); closePanel(el.steamPanel);
  closePanel(el.localePanel);
  closePanel(el.vntextPanel);
  closePanel(el.getPanel);
  el.moreMenu.hidden = true;
  el.sortMenu.hidden = true;
  el.addMenu.hidden = true;
  el.scopeMenu.hidden = true;
};
