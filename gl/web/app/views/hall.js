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

/* ------------------------------------------------------------------ *
 * 环的几何：角度/半径/透视这些**常量**，以及「按视口算尺寸」的纯计算。
 * 运行期状态（float/target/items/nodes…）留在主模块，动画与拖拽照旧由它写。
 * ------------------------------------------------------------------ */

/** 环的几何常量（基准窗口 1380×690 下的像素值）。 */
export const RING_GEOMETRY = {
  step: 16,        // 相邻两张封面绕竖轴的角度（度）
  rx: 580,         // 水平半径（基准窗口下的像素）
  rz: 260,         // 纵深半径
  depth: 1100,     // 透视距离
  span: 4.6,       // 可见的半边张数，再远就藏起来（绕到背面）
  shrink: 0.24,    // 每远一格额外缩小的比例（透视之外再补一点）
  y: 36,           // 整圈封面的重心（相对舞台中心下移，避开顶部工具条）
  tau: 0.13,       // 回弹时间常数（秒），越小越干脆
  dragPx: 112,     // 横向拖动多少像素换一张
};

/** 基准封面尺寸（unit=1 时）。 */
export const RING_BASE = { w: 180, h: 270 };

/**
 * 按视口算这一帧的环尺寸：窗口越窄，半径与封面一起收，
 * 保证一圈封面仍是同样的构图。
 *
 * 纯函数：视口尺寸与 clamp 都由调用方给，方便单独验证。
 */
export function ringGeometryOf({ viewportWidth, viewportHeight, geometry = RING_GEOMETRY,
                                 base = RING_BASE, clamp }) {
  const vw = viewportWidth || 1380;
  const vh = viewportHeight || 690;
  const unit = clamp(Math.min(vw / 1380, vh / 690), 0.6, 1.3);
  return {
    unit,
    w: Math.round(base.w * unit),
    h: Math.round(base.h * unit),
    rx: geometry.rx * unit,
    rz: geometry.rz * unit,
    depth: geometry.depth * unit,
  };
}

/**
 * 把一张封面放到环上的第 r 格（r = 相对当前位置的**浮点**格数）。
 *
 * 纯「输入 → 样式」映射：读 `ring`（常量）与 `size`（这一帧的尺寸），写节点样式。
 * 帧循环本身仍在主模块 —— 这里只负责单张卡片的几何与明暗，方便单独验证。
 */
export function placeRingTile(node, r, { ring, size }) {
  const a = Math.abs(r);
  if (a > ring.span) {
    if (node.dataset.ringHidden !== "1") {
      node.dataset.ringHidden = "1";
      node.style.visibility = "hidden";
      node.style.opacity = "0";
      node.style.pointerEvents = "none";
      node.style.willChange = "";
    }
    return;
  }
  if (node.dataset.ringHidden === "1") {
    node.dataset.ringHidden = "0";
    node.style.visibility = "";
    node.style.pointerEvents = "";
    node.style.willChange = "transform, opacity";
  }
  const deg = r * ring.step;
  const rad = deg * Math.PI / 180;
  const z = Math.cos(rad) * size.rz;
  // 近大远小由父级的 perspective 负责（translateZ 已经带出透视），
  // 这里只补一点额外收缩，让离焦点越远的封面明显更小
  const scale = 1 / (1 + ring.shrink * a);
  const x = Math.sin(rad) * size.rx;
  const y = ring.y - 12 * Math.max(0, 1 - a) + 14 * (1 - Math.cos(rad));
  const opacity = a <= 2 ? 1 : Math.max(0.14, 1 - (a - 2) * 0.34);
  const veil = a < 0.5 ? a * 0.5 : Math.min(0.62, 0.25 + (a - 0.5) * 0.08);
  const blur = Math.max(0, a - 3) * 0.45;
  node.style.transform =
    `translate(-50%,-50%) translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,${z.toFixed(1)}px) ` +
    `rotateY(${deg.toFixed(2)}deg) scale(${scale.toFixed(4)})`;
  node.style.opacity = opacity.toFixed(3);
  node.style.zIndex = String(200 - Math.round(a * 20));
  node.style.filter = blur > 0.02 ? `blur(${blur.toFixed(2)}px)` : "";
  node.style.setProperty("--veil", veil.toFixed(3));
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
