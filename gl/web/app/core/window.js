/* Aurora 前端 · 窗口拖拽 / 缩放 / 标题栏按钮（P4.3-s）
 *
 * 从主模块搬出来的一块「窗口外壳」逻辑：无边框窗口的拖动、四周缩放、
 * 最小化 / 最大化 / 关闭，以及「鼠标在窗口外松开」时的状态清理。
 *
 * 指针状态（drag / resize）现在是模块内部私有；大厅的划封面拖动由
 * ctx.onPointerReset 通知（主模块传 `() => ring.endDrag()`）。
 */
import { call } from "./api.js";
import { $ } from "./dom.js";

export function bindWindowControls(ctx) {
  let drag = null;
  let resize = null;

  $("btnMin").onclick = () => call("window_cmd", "minimize");
  $("btnMax").onclick = () => call("window_cmd", "toggle_maximize");
  $("btnClose").onclick = () => call("window_cmd", "close");

  document.addEventListener("mousedown", async (e) => {
    if (e.button !== 0) return;

    const rz = e.target.closest(".rz");
    if (rz) {
      e.preventDefault();
      resize = { edge: rz.dataset.edge, sx: e.screenX, sy: e.screenY, base: null, queued: false };
      resize.base = await call("resize_start");
      return;
    }

    const handle = e.target.closest("[data-drag]");
    if (!handle) return;
    if (e.target.closest("[data-nodrag],button,input,select,textarea,a,.gi,.bg-item,.match-item")) return;
    e.preventDefault();
    drag = { sx: e.screenX, sy: e.screenY, queued: false };
    await call("drag_start");
  });

  document.addEventListener("mousemove", (e) => {
    if (resize && resize.base) {
      if (resize.queued) return;
      resize.queued = true;
      const sx = e.screenX, sy = e.screenY;
      requestAnimationFrame(() => {
        resize.queued = false;
        if (!resize || !resize.base) return;
        const d = window.devicePixelRatio || 1;
        const dx = (sx - resize.sx) * d;
        const dy = (sy - resize.sy) * d;
        const b = resize.base;
        let { x, y, w, h } = b;
        if (resize.edge.includes("e")) w = b.w + dx;
        if (resize.edge.includes("s")) h = b.h + dy;
        if (resize.edge.includes("w")) { w = b.w - dx; x = b.x + dx; }
        if (resize.edge.includes("n")) { h = b.h - dy; y = b.y + dy; }
        call("resize_apply", Math.round(x), Math.round(y), Math.round(w), Math.round(h),
             resize.edge);
      });
      return;
    }
    if (drag) {
      if (drag.queued) return;
      drag.queued = true;
      const dx = e.screenX - drag.sx;
      const dy = e.screenY - drag.sy;
      requestAnimationFrame(() => {
        drag.queued = false;
        if (drag) call("drag_move", dx * (window.devicePixelRatio || 1),
                       dy * (window.devicePixelRatio || 1));
      });
    }
  });

  /* 鼠标在窗口外松开、或窗口切走时收不到 mouseup，状态必须主动清掉，
     否则会出现「没按键也在拖窗口 / 划封面」这种鬼畜行为 */
  function dropPointerState() {
    if (drag) { drag = null; call("drag_end"); }
    if (resize) { resize = null; }
    ctx.onPointerReset();
  }
  document.addEventListener("mouseup", dropPointerState);
  window.addEventListener("blur", dropPointerState);
  document.addEventListener("mouseleave", dropPointerState);

  // 双击拖拽区域最大化 / 还原
  document.addEventListener("dblclick", (e) => {
    if (e.target.closest("[data-drag]") &&
        !e.target.closest("[data-nodrag],button,input,select,a,.gi")) {
      call("window_cmd", "toggle_maximize");
    }
  });
}
