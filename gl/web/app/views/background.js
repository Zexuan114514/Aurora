/* Aurora 前端 · 背景层与背景面板（P4.3-s）
 *
 * 背景是两块叠在一起的层（a / b）：换图时先让下一层加载好再淡入，
 * 所以「当前是哪一层」「当前是哪张图」这些状态跟着一起搬过来了。
 *
 * 这里管的是：
 *   - `applyBackground` / `applyBgView`：换图与缩放（含图片预加载与失败提示）
 *   - `scheduleBackground`：焦点变化后延迟淡入 + 预取左右邻居
 *   - `fallbackBackground`：没有壁纸时按名字取一个渐变色兜底
 *   - 背景面板的按钮、缩放滑杆与全局图片回退链（`data-srcs`）
 *
 * ctx = { currentGame, hallKeys, syncBgZoomUi, renderBgPanel, toast }
 */
import { call } from "../core/api.js";
import { $, el } from "../core/dom.js";
import { closeAll, closePanel, openPanel } from "../core/panels.js";
import { state } from "../core/store.js";
import { ringMod } from "./hall.js";

/** 按名字取一个稳定的色相，用作没有壁纸时的渐变兜底。 */
function hashHue(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) % 360;
  return h;
}

const cssUrl = (u) => `url("${String(u).replace(/"/g, '\\"')}")`;

export function fallbackBackground(game) {
  const hue = hashHue(game.name || game.id || "aurora");
  return `linear-gradient(150deg,
    hsl(${hue} 46% 26%) 0%,
    hsl(${(hue + 42) % 360} 40% 15%) 48%,
    hsl(${(hue + 96) % 360} 34% 9%) 100%)`;
}

/* 空库时的默认极光背景（当前由页面样式兜底，这里保留给代码侧复用） */
export const DEFAULT_BACKGROUND = [
  "radial-gradient(120% 92% at 12% 4%, rgba(38,66,150,.85) 0%, rgba(38,66,150,0) 56%)",
  "radial-gradient(108% 82% at 90% 8%, rgba(104,52,140,.78) 0%, rgba(104,52,140,0) 58%)",
  "radial-gradient(130% 100% at 52% 112%, rgba(14,86,110,.72) 0%, rgba(14,86,110,0) 62%)",
  "linear-gradient(162deg, #0b1024 0%, #080a15 52%, #05050a 100%)",
].join(", ");

export function createBackgroundView(ctx) {
  let bgCurrent = null;      // 当前显示的图（同图只更新缩放，不重新淡入）
  let bgSide = "a";          // 当前显示的是哪一层
  let bgTimer = null;        // 焦点切换后的背景防抖
  let bgViewTimer = null;    // 缩放持久化的防抖

  const bgLayer = () => (bgSide === "a" ? $("bg-a") : $("bg-b"));

  function bgViewOf(game) {
    return {
      scale: Math.max(1, Number(game && game.bg_scale) || 1),
      x: 0,
      y: 0,
    };
  }

  function bgTransform(view) {
    return view.scale === 1 && !view.x && !view.y
      ? "" : `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})`;
  }

  function applyBgView(view, layer) {
    (layer || bgLayer()).style.transform = bgTransform(view);
  }

  function applyBackground(source, view, animate = true) {
    const a = $("bg-a"), b = $("bg-b");
    const cur = bgSide === "a" ? a : b;
    const nxt = bgSide === "a" ? b : a;
    if (bgCurrent === source) { applyBgView(view, cur); return; }
    bgCurrent = source;

    if (!source) {
      cur.classList.remove("on");
      nxt.classList.remove("on");
      return;
    }

    const isGradient = source.startsWith("linear-gradient") || source.startsWith("radial-gradient");
    const ken = !!state.settings.ken_burns && !isGradient;

    const swap = () => {
      const inner = nxt.querySelector(".bg-img");
      inner.style.backgroundImage = isGradient ? source : cssUrl(source);
      inner.classList.toggle("ken", ken);
      applyBgView(view, nxt);
      void nxt.offsetWidth;
      nxt.classList.add("on");
      if (animate) cur.classList.remove("on");
      else { cur.classList.remove("on"); nxt.style.transition = "none"; void nxt.offsetWidth; nxt.style.transition = ""; }
      bgSide = bgSide === "a" ? "b" : "a";
    };

    if (isGradient) { swap(); return; }
    const probe = new Image();
    probe.onload = swap;
    probe.onerror = () => { bgCurrent = null; ctx.toast("背景图加载失败"); };
    probe.src = source;
  }

  /** 焦点变化 → 背景延迟淡入 + 预取左右邻居。 */
  function scheduleBackground() {
    const game = ctx.currentGame();
    if (!game) return;
    clearTimeout(bgTimer);
    bgTimer = setTimeout(() => {
      applyBackground(game.background || fallbackBackground(game), bgViewOf(game));
      // 预取左右邻居（环上就是前后各一张，首尾相接）
      const keys = ctx.hallKeys();
      const index = Math.max(0, keys.indexOf(state.focus));
      [-1, 1].forEach((d) => {
        const near = state.games.find((g) => g.id === keys[ringMod(index + d, keys.length)]);
        if (near && near.background) { const img = new Image(); img.src = near.background; }
      });
    }, 140);
  }

  /* 修改当前游戏的背景缩放（缩放只由滑杆控制） */
  function updateBgView(next, persist = true) {
    const g = ctx.currentGame();
    if (!g) return;
    const view = { scale: Math.max(1, Math.min(3, Number(next.scale) || 1)), x: 0, y: 0 };
    g.bg_scale = view.scale;
    g.bg_x = 0;
    g.bg_y = 0;
    applyBgView(view);
    ctx.syncBgZoomUi(g);
    if (!persist) return;
    clearTimeout(bgViewTimer);
    bgViewTimer = setTimeout(() => {
      call("set_background_view", g.id, g.bg_scale, g.bg_x, g.bg_y).catch(() => {});
    }, 350);
  }

  /** 设置页改「Ken Burns」时，立即作用在当前背景层上。 */
  function applyKenBurns(on) {
    const inner = bgLayer().querySelector(".bg-img");
    if (inner) inner.classList.toggle("ken", !!on);
  }

  async function chooseBackground(url, kind) {
    const g = ctx.currentGame();
    if (!g) return;
    g.background = url;
    g.background_kind = kind;
    applyBackground(url, bgViewOf(g));
    ctx.renderBgPanel();
    await call("set_background", g.id, url, kind);
  }

  async function pickLocalBackground() {
    const g = ctx.currentGame();
    if (!g) return;
    const res = await call("pick_local_background", g.id);
    if (!res || res.cancelled) return;
    if (!res.ok) { ctx.toast("选择失败：" + (res.error || "")); return; }
    Object.assign(g, res.game);
    applyBackground(g.background, bgViewOf(g));
    ctx.renderBgPanel();
    ctx.toast("已应用本地背景图");
  }

  function bind() {
    // 图片加载失败 -> 依次尝试备用地址，全部失败则显示占位
    document.addEventListener("error", (e) => {
      const img = e.target;
      if (!img || img.tagName !== "IMG" || !img.dataset) return;
      let chain = [];
      try { chain = JSON.parse(img.dataset.srcs || "[]"); } catch (_) { chain = []; }
      if (chain.length) {
        img.dataset.srcs = JSON.stringify(chain.slice(1));
        img.src = chain[0];
        return;
      }
      img.classList.add("img-broken");
      const holder = img.parentElement;
      if (holder) holder.classList.add("img-broken");
      const item = img.closest(".bg-item, .gi-cover");
      if (item) item.classList.add("img-broken");
    }, true);

    // 背景面板
    $("btnBackgrounds").onclick = () => {
      const opening = !el.bgPanel.classList.contains("open");
      closeAll();
      if (opening) { ctx.renderBgPanel(); openPanel(el.bgPanel); }
    };
    $("bgClose").onclick = () => closePanel(el.bgPanel);
    el.bgGrid.addEventListener("click", (e) => {
      const item = e.target.closest(".bg-item");
      if (item) chooseBackground(item.dataset.url, item.dataset.kind);
    });
    $("btnLocalBg").onclick = () => pickLocalBackground();
    $("btnResetBg").onclick = async () => {
      const g = ctx.currentGame();
      if (!g) return;
      const res = await call("clear_background", g.id);
      if (res.game) Object.assign(g, res.game);
      const first = (g.images || [])[0];
      if (first) { g.background = first.url; g.background_kind = first.kind; }
      g.bg_scale = 1; g.bg_x = 0; g.bg_y = 0;
      applyBackground(g.background || fallbackBackground(g), { scale: 1, x: 0, y: 0 });
      ctx.syncBgZoomUi(g);
      ctx.renderBgPanel();
    };

    // 面板里的缩放滑杆
    $("bgZoom").oninput = (e) => {
      if (!ctx.currentGame()) return;
      updateBgView({ scale: Number(e.target.value) / 100 }, false);
    };
    $("bgZoom").onchange = (e) => {
      if (!ctx.currentGame()) return;
      updateBgView({ scale: Number(e.target.value) / 100 });
    };
    $("bgViewReset").onclick = () => {
      updateBgView({ scale: 1 });
      ctx.toast("背景已复位");
    };
  }

  return { bind, scheduleBackground, chooseBackground, pickLocalBackground, applyKenBurns };
}
