/* Aurora 前端 · 大厅视图（P4.3-d … P4.3-j）
 *
 * 这一路刀把大厅整块收进模块：
 *   P4.3-d 自检读出面（`window.__aurora.ring()` / `layout()` 的取数）
 *   P4.3-e 环几何常量与纯计算
 *   P4.3-f 单张封面的环变换
 *   P4.3-g 环的叶子 helper
 *   P4.3-h 样式应用与键列表
 *   P4.3-i 平铺布局排布
 *   P4.3-j 环本体：运行期状态 + 帧循环 + 拖动 / 滚轮 / 快捷键
 *
 * 顶部的纯函数刻意**不 import 任何东西**：依赖全部由调用方传入，模块初始化
 * 阶段不存在 TDZ 风险（P4.3-c 踩过 ctx 的坑）。底部的 `createRing(ctx)` 才
 * 需要界面元素与状态，也只 import `core/`（视图不反向依赖主模块）。
 */
import { $, el } from "../core/dom.js";
import { state } from "../core/store.js";

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

/* ------------------------------------------------------------------ *
 * 环用到的几个叶子 helper：循环取模、把差值折到 [-n/2, n/2)、清掉环样式。
 * 都是纯函数/纯 DOM 清理，不碰帧循环语义（帧循环本身仍在主模块）。
 * ------------------------------------------------------------------ */

/** 环上的循环取模（负数也要落到 [0, n)）。 */
export const ringMod = (i, n) => ((i % n) + n) % n;

/** 把差值折到 [-n/2, n/2)：第 i 项相对当前位置在第几圈、哪个方向。 */
export const ringSigned = (d, n) => {
  const m = ringMod(d, n);
  return m > n / 2 ? m - n : m;
};

/** 清掉一张封面上的环样式（切到平铺布局、或节点要重用时调）。 */
export function clearRingStyles(node) {
  for (const prop of ["transform", "opacity", "filter", "zIndex", "visibility",
                      "willChange", "transition", "pointerEvents"]) {
    node.style.removeProperty(prop.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase()));
  }
  node.style.removeProperty("--veil");
  delete node.dataset.ringHidden;
}

/** 把这一帧算出的环尺寸写到样式变量上（布局用它给封面定尺寸与透视）。 */
export function applyRingSize({ row, viewport, size }) {
  row.style.setProperty("--gi-w", size.w + "px");
  row.style.setProperty("--gi-h", size.h + "px");
  viewport.style.setProperty("--ring-d", Math.round(size.depth) + "px");
}

/**
 * 大厅里该排的键列表：所有可见游戏 + 末尾的「＋ 导入游戏」。
 *
 * 纯函数：可见游戏由调用方按当前筛选/排序算好后传进来，本模块不碰 store。
 */
export function hallKeysOf(visibleIds, addKey) {
  const ids = [...visibleIds];
  ids.push(addKey);
  return ids;
}

/**
 * 平铺布局的排布：把「焦点那张」对到视口中央，其余靠 CSS 横滑。
 *
 * 上下文全部传入（row / viewport / keys / focus / ring 运行期对象），
 * 同时把 ring.float/target 对齐到焦点索引 —— 这样切回环形布局时从这里接着转。
 * 返回是否真的摆了位（焦点不在列表里就返回 false，调用方无需另外判断）。
 */
export function updateFlatRow({ row, viewport, keys, focus, ring, instant = false }) {
  const index = keys.indexOf(focus);
  if (index < 0) return false;
  const tile = row.children[index];
  if (!tile) return false;
  for (const node of row.children) {
    if (node.dataset.ringHidden === "1" || node.style.transform) clearRingStyles(node);
  }
  const noAnim = instant || !ring.flatReady;
  if (noAnim) {
    ring.flatReady = true;
    row.style.transition = "none";
  }
  const rect = viewport.getBoundingClientRect();
  const center = tile.offsetLeft + tile.offsetWidth / 2;
  row.style.transform = `translate3d(${Math.round(rect.width / 2 - center)}px, 0, 0)`;
  if (noAnim) requestAnimationFrame(() => { row.style.transition = ""; });
  ring.float = ring.target = index;   // 切回环形时从这里接着转
  return true;
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

/* ------------------------------------------------------------------ *
 * 环本体（P4.3-j）：运行期状态、帧循环，以及拖动 / 滚轮 / 快捷键。
 *
 * 这一刀把「谁在转这个环」整个收进模块：RING 运行期对象、测量、节点同步、
 * 帧循环（ringFrame/ringRun）、两种布局的重新摆位，还有指针与键盘输入。
 * 主模块只留内容与副作用（封面模板、焦点 UI、背景调度、进游戏页），
 * 通过 ctx 回调交接 —— 视图不反向 import 主模块（P4.3-b 的约定）。
 *
 *   ctx = {
 *     addKey,          // 「＋ 导入游戏」那一格的键
 *     keys(),          // 当前该排的键列表（可见游戏 + addKey，由主模块筛/排）
 *     tile(key),       // 一格的 { html, busy, title }
 *     onFocus(key, opts),  // 换焦点（主模块的 setFocus）
 *     onEnter(id?),    // 进游戏页（id 省略 = 当前焦点）
 *     onPlay(id?),     // 开始 / 结束游戏（id 省略 = 当前焦点那款）
 *     onAddMenu(tile), // 打开「导入本地 / 获取游戏」菜单
 *   }
 *
 * 注意：ctx 里一律用**箭头延迟取值**包装主模块的函数（P4.3-c 的 TDZ 教训）。
 * ------------------------------------------------------------------ */
export function createRing(ctx) {
  const { addKey, keys: keysOf, tile: tileOf, onFocus, onEnter, onPlay, onAddMenu } = ctx;

  /* 运行期状态：几何常量来自 RING_GEOMETRY，其余是位置 / 节点 / 帧循环 */
  const RING = {
    ...RING_GEOMETRY,
    items: [],        // [{key, node, sig, index}]，index 就是环上的位置
    nodes: new Map(), // key -> item，重建列表时复用节点，动画不中断
    keysSig: "",
    float: 0,         // 当前转动到的位置（浮点，可以停在两张之间）
    target: 0,        // 目标位置（整数）
    raf: 0,
    last: 0,
    ready: false,
    flatReady: false, // 平铺布局是否已经就位（首次直接就位、之后才做动画）
    dragActive: false,
  };
  let ringSize = {unit: 1, w: 180, h: 270, rx: 580, rz: 260, depth: 1100};
  let swipe = null;      // 横向拖动中的手势状态
  let swipeEnd = null;   // 松手 / 失焦时的吸附（bind 时装上）
  let hoverTimer = null;
  let moved = false;     // 这一次按下是「拖了一把」还是「点了一下」
  let wheelLast = 0;     // 滚轮节流：一次滚动只翻一张

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const flat = () => state.settings.hall_layout === "flat";
  const layoutName = () => (flat() ? "flat" : "ring");

  /* 窗口越窄，半径与封面一起收，保证一圈封面仍然是同样的构图 */
  function ringGeometry() {
    const vp = el.hallViewport;
    const vw = (vp && vp.clientWidth) || window.innerWidth || 1380;
    const vh = (vp && vp.clientHeight) || Math.max(420, (window.innerHeight || 880) - 170);
    return ringGeometryOf({ viewportWidth: vw, viewportHeight: vh,
                            geometry: RING, base: RING_BASE, clamp });
  }

  function measure() {
    ringSize = ringGeometry();
    applyRingSize({ row: el.hallRow, viewport: el.hallViewport, size: ringSize });
  }

  /* 把一张封面放到环上的第 r 格（r 为相对当前位置的浮点格数） */
  const place = (node, r) => placeRingTile(node, r, { ring: RING, size: ringSize });

  function frame(ts) {
    const n = RING.items.length;
    if (!n) {                       // 没有封面就不用转了
      RING.raf = 0;
      return;
    }
    if (flat()) {                   // 平铺布局下环不再转
      RING.raf = 0;
      return;
    }
    if (!RING.last) RING.last = ts;
    const dt = clamp((ts - RING.last) / 1000, 0.001, 0.05);
    RING.last = ts;
    if (!RING.dragActive) {
      RING.float += (RING.target - RING.float) * (1 - Math.exp(-dt / RING.tau));
      if (Math.abs(RING.target - RING.float) < 0.002) RING.float = RING.target;
    }
    for (const item of RING.items) place(item.node, ringSigned(item.index - RING.float, n));
    if (RING.dragActive || Math.abs(RING.target - RING.float) > 0.0005) {
      RING.raf = requestAnimationFrame(frame);
    } else {
      RING.raf = 0;
      RING.last = 0;
    }
  }

  function run() {
    if (!RING.raf) {
      RING.last = 0;
      RING.raf = requestAnimationFrame(frame);
    }
  }

  /* 把节点和当前列表对齐：复用已有节点，内容变了才重写，顺序变了才搬动。
     返回列表是否变了（调用方据此决定要不要直接就位，免得从旧位置转一大圈）。 */
  function sync(keys) {
    const sig = keys.join("|");
    const listChanged = sig !== RING.keysSig;
    RING.keysSig = sig;
    const wanted = new Set(keys);
    for (const [key, item] of [...RING.nodes]) {
      if (!wanted.has(key)) {
        item.node.remove();
        RING.nodes.delete(key);
      }
    }
    RING.items = keys.map((key, index) => {
      const info = tileOf(key);
      let item = RING.nodes.get(key);
      if (!item) {
        const node = document.createElement("button");
        node.type = "button";
        node.className = "gi" + (key === addKey ? " gi-add" : "") + (info.busy ? " searching" : "");
        node.dataset.key = key;
        if (key === addKey) node.dataset.add = "1";
        else node.dataset.id = key;
        node.innerHTML = info.html;
        el.hallRow.appendChild(node);
        item = {key, node, sig: info.html, index};
        RING.nodes.set(key, item);
      } else {
        if (item.sig !== info.html) {
          item.node.innerHTML = info.html;
          item.sig = info.html;
        }
        item.node.classList.toggle("searching", !!info.busy);
      }
      item.node.title = info.title;
      item.index = index;
      return item;
    });
    let cursor = el.hallRow.firstChild;
    for (const item of RING.items) {
      if (item.node === cursor) {
        cursor = cursor.nextSibling;
        continue;
      }
      el.hallRow.insertBefore(item.node, cursor);
    }
    return listChanged;
  }

  /** 库空了：节点与缓存全清掉（下次重建）。 */
  function clear() {
    RING.items = [];
    for (const item of RING.nodes.values()) item.node.remove();
    RING.nodes.clear();
    RING.keysSig = "";
  }

  const indexOf = (key) => RING.items.findIndex((item) => item.key === key);

  /* 让环转到当前焦点；instant 用于首帧、换筛选、窗口缩放这类不该有动画的场合 */
  function update(instant = false) {
    if (flat()) {
      updateFlatRow({ row: el.hallRow, viewport: el.hallViewport, keys: keysOf(),
                      focus: state.focus, ring: RING, instant });
      return;
    }
    measure();
    const index = indexOf(state.focus);
    const n = RING.items.length;
    if (index < 0 || !n) return;
    if (instant || !RING.ready) {
      RING.float = index;
      RING.target = index;
      RING.ready = true;
    } else {
      // 走最近的那一边：在第一张按 ← 时向后退一格露出最后一张，
      // 而不是一路正转一整圈
      RING.target = RING.float + ringSigned(index - RING.float, n);
    }
    run();
  }

  /* 布局切换：清掉另一套布局留下的内联样式再重新摆位 */
  function applyLayout() {
    const isFlat = flat();
    document.body.classList.toggle("hall-flat", isFlat);
    if (isFlat) {
      for (const node of el.hallRow.children) clearRingStyles(node);
      RING.flatReady = false;
    } else {
      RING.ready = false;
      RING.float = RING.target = Math.max(0, keysOf().indexOf(state.focus));
    }
    update(true);
  }

  /* 方向键 / 滚轮：走到头就从另一侧绕回来（循环队列） */
  function move(delta) {
    const keys = keysOf();
    if (!keys.length || !delta) return;
    const index = keys.indexOf(state.focus);
    const base = index < 0 ? 0 : index;
    // 平铺布局不循环：到第一张 / 最后一张就停住
    const next = flat()
      ? Math.min(keys.length - 1, Math.max(0, base + delta))
      : ringMod(base + delta, keys.length);
    if (next !== index) onFocus(keys[next]);
    else if (!RING.dragActive) update();
  }

  function jump(edge) {
    const keys = keysOf();
    if (!keys.length) return;
    onFocus(edge === "end" ? keys[keys.length - 1] : keys[0]);
  }

  /** 大厅快捷键：← → / Home / End / Enter。返回是否消费了这次按键。 */
  function handleKey(e) {
    if (e.key === "ArrowLeft") { e.preventDefault(); move(-1); return true; }
    if (e.key === "ArrowRight") { e.preventDefault(); move(1); return true; }
    if (e.key === "Home") { e.preventDefault(); jump("start"); return true; }
    if (e.key === "End") { e.preventDefault(); jump("end"); return true; }
    if (e.key !== "Enter") return false;
    e.preventDefault();
    if (state.page === "game") onPlay();
    else if (state.focus === addKey) {
      const tile = el.hallRow.querySelector(".gi-add");
      if (tile) onAddMenu(tile);
    } else onEnter();
    return true;
  }

  /* 输入绑定：主模块在 bindUi 里调一次（时机与拆分前一致） */
  function bind() {
    // 悬停 0.3 秒自动聚焦
    el.hallRow.addEventListener("mousemove", (e) => {
      if (RING.dragActive) return;
      const tile = e.target.closest(".gi");
      if (!tile) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(() => {
        if (state.settingsOpen || state.view === "categories") return;
        const key = tile.dataset.add ? addKey : tile.dataset.id;
        if (key && key !== state.focus) onFocus(key);
      }, 320);
    });
    el.hallRow.addEventListener("mouseleave", () => clearTimeout(hoverTimer));
    // 单击进游戏页 / 双击直接开玩（刚拖过的那一下不算）
    el.hallRow.addEventListener("click", (e) => {
      const tile = e.target.closest(".gi");
      if (!tile || moved) return;
      if (tile.dataset.add) { onAddMenu(tile); return; }
      onEnter(tile.dataset.id);
    });
    el.hallRow.addEventListener("dblclick", (e) => {
      const tile = e.target.closest(".gi");
      if (!tile || tile.dataset.add || moved) return;
      onPlay(tile.dataset.id);
    });

    // 横向拖动 = 手指带着封面环转，松手吸附到最近的一张
    const swipeStart = (e) => {
      if (e.button !== 0) return;
      // 关键：每次左键按下都先复位「这次是拖拽还是单击」。
      // 不复位的话，拖过一次之后 moved 永远为 true，之后所有单击都会被当成拖拽丢掉。
      moved = false;
      if (state.settingsOpen || state.view === "categories") return;
      // 工具条 / 底部信息带是拖窗口的区域，别在这里抢滑动
      if (e.target.closest("a, input, select, textarea, .pill, [data-drag], .rz")) return;
      // 封面本身可以抓（最自然的手势），其它按钮（获取游戏 / 排序 / 窗口按钮…）不抢
      if (e.target.closest("button") && !e.target.closest(".gi")) return;
      swipe = {x: e.clientX, y: e.clientY, base: e.clientX, start: RING.float, active: false,
               flat: flat(), baseX: 0, dx: 0};
    };
    const swipeMove = (e) => {
      if (!swipe) return;
      if (state.settingsOpen || state.view === "categories") { swipe = null; return; }
      const dx = e.clientX - swipe.base;
      const dy = e.clientY - swipe.y;
      if (!swipe.active) {
        // 先分清「点一下」和「拖一把」：7px 以内、竖向占优都不算拖
        if (Math.abs(dx) < 7 || Math.abs(dx) <= Math.abs(dy)) return;
        swipe.active = true;
        moved = true;
        RING.dragActive = true;
        el.hallRow.classList.add("ring-drag");
        clearTimeout(hoverTimer);
      }
      const pos = swipe.start - dx / (RING.dragPx * ringSize.unit);
      if (swipe.flat) {
        // 平铺布局：行直接跟手平移，松手再吸附到最近一张
        if (!swipe.baseX) {
          const match = /translate3d\((-?[\d.]+)px/.exec(el.hallRow.style.transform || "");
          swipe.baseX = match ? Number(match[1]) : 0;
        }
        swipe.dx = dx;
        el.hallRow.style.transition = "none";
        el.hallRow.style.transform = `translate3d(${Math.round(swipe.baseX + dx)}px, 0, 0)`;
        return;
      }
      RING.float = RING.target = pos;
      run();
      // 底部信息带 / 背景跟着最近的一张走
      const items = RING.items;
      if (items.length) {
        const near = items[ringMod(Math.round(pos), items.length)];
        if (near && near.key !== state.focus) onFocus(near.key, {scroll: false});
      }
    };
    swipeEnd = () => {
      if (!swipe) return;
      const {active, flat: wasFlat, dx: dragDx} = swipe;
      swipe = null;
      if (!active) return;
      RING.dragActive = false;
      el.hallRow.classList.remove("ring-drag");
      if (wasFlat) {
        // 跟手位移换算成「翻了几张」，再回到聚焦动画
        const tile = el.hallRow.querySelector(".gi") || el.hallRow.firstChild;
        const step = (tile ? tile.getBoundingClientRect().width : 172) + 24;
        const steps = Math.round(-(dragDx || 0) / Math.max(40, step));
        el.hallRow.style.transition = "";
        if (steps) move(steps);
        update(true);
        return;
      }
      RING.target = Math.round(RING.float);
      run();
      const n = RING.items.length;
      if (n) {
        const near = RING.items[ringMod(RING.target, n)];
        if (near) onFocus(near.key, {scroll: false});
      }
    };
    // 捕获阶段：保证在任何其它 mousedown 处理（窗口拖拽等）之前先把状态复位
    $("app").addEventListener("mousedown", swipeStart, true);
    document.addEventListener("mousemove", swipeMove);

    // 滚轮 / 横向滚动 = 切换游戏（大厅与游戏页一致）
    $("app").addEventListener("wheel", (e) => {
      // 设置页 / 分类工作区里滚轮只滚动各自的内容
      if (state.settingsOpen || state.view === "categories") return;
      if (e.target.closest(".sheet, .menu, .modal, input, select, textarea, #toolbar, #toast")) return;
      if (!state.games.length) return;
      e.preventDefault();
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      const now = Date.now();
      if (now - wheelLast < 130) return;
      if (Math.abs(delta) < 2) return;
      wheelLast = now;
      move(delta > 0 ? 1 : -1);
    }, { passive: false });
  }

  return {
    bind,
    sync,
    clear,
    update,
    measure,
    run,
    applyLayout,
    move,
    jump,
    handleKey,
    /* 鼠标在窗口外松开 / 窗口切走时，主模块要用它把吸附补上 */
    endDrag: () => { if (swipeEnd) swipeEnd(); },
    dragging: () => RING.dragActive,
    layoutName,
    /* 自检读出面：`window.__aurora.ring()` 用它，返回结构与拆分前一致 */
    readout: () => ringReadout({ RING, state }),
  };
}
