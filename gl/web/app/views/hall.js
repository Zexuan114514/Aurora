/* Aurora 前端 · 大厅视图（P4.3-d 第一刀）
 *
 * 这一刀先把**自检读出面**搬出来：`window.__aurora.ring()` 与 `layout()` 是
 * e2e / visual 的判据来源，逻辑纯读、无副作用，最适合先独立成模块。
 * 环动画、拖拽与键盘导航（RING 的写入方）下一刀再搬。
 *
 * 这两个函数刻意**不 import 任何东西**：所有依赖都由调用方传进来，
 * 于是模块初始化阶段不存在 TDZ 之类的风险（P4.3-c 踩过 ctx 的坑）。
 */

/** 环形队列的当前状态（位置 / 目标 / 顺序 / 是否在拖动）。 */
export function ringReadout({ RING, state }) {
  return {
    float: Number(RING.float.toFixed(3)),
    target: RING.target,
    drag: RING.dragActive,
    focus: state.focus,
    keys: RING.items.map((item) => item.key),
  };
}

/** 当前主页布局 + 平铺布局下每张封面的实际位置（全部是读 DOM）。 */
export function layoutReadout({ row, viewport, layoutName, flatClass }) {
  return {
    name: layoutName,
    flatClass,
    rowTransform: row.style.transform || "",
    viewportWidth: Math.round(viewport.width),
    tiles: [...row.children].map((node) => {
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        key: node.dataset.add ? "__add__" : (node.dataset.id || ""),
        center: Math.round(rect.left + rect.width / 2 - viewport.left),
        width: Math.round(rect.width),
        transform: style.transform,
        visible: style.visibility !== "hidden" && Number(style.opacity) > 0.05,
        focus: node.classList.contains("focus"),
      };
    }),
  };
}
