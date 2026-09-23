<template>
  <div id="bg-root" aria-hidden="true">
    <div ref="layerA" id="bg-a" class="bg-layer">
      <div ref="imageA" class="bg-img" />
    </div>
    <div ref="layerB" id="bg-b" class="bg-layer">
      <div ref="imageB" class="bg-img" />
    </div>
    <div id="bg-scrim" />
    <div id="bg-vignette" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue"
import { fixAssetUrl } from "@/core/assets"
import { emitUi, onUi } from "@/core/bus"
import { state, toast } from "@/core/store"
import { ringMod } from "@/features/hall/geometry"
import { bgViewOf, cssUrl, fallbackBackground } from "@/features/background"

const layerA = ref<HTMLElement>()
const layerB = ref<HTMLElement>()
const imageA = ref<HTMLElement>()
const imageB = ref<HTMLElement>()

let current: string | null = null
let side: "a" | "b" = "a"
let timer: number | undefined
let viewTimer: number | undefined

const layer = () => (side === "a" ? imageA.value : imageB.value)?.parentElement as HTMLElement
const inner = () => (side === "a" ? imageA.value : imageB.value) as HTMLElement

function applyView(view: { scale: number; x: number; y: number }, target?: HTMLElement) {
  const node = target || layer()
  if (!node) return
  node.style.transform = view.scale === 1 && !view.x && !view.y
    ? "" : `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})`
}

function applyBackground(source: string | null, view: { scale: number; x: number; y: number }, animate = true) {
  if (!layerA.value || !layerB.value) return
  const cur = side === "a" ? layerA.value : layerB.value
  const nxt = side === "a" ? layerB.value : layerA.value
  if (current === source) { applyView(view, cur); return }
  current = source
  if (!source) {
    cur.classList.remove("on")
    nxt.classList.remove("on")
    return
  }
  const isGradient = source.startsWith("linear-gradient") || source.startsWith("radial-gradient")
  const ken = !!state.settings.ken_burns && !isGradient
  const swap = () => {
    const node = nxt.querySelector(".bg-img") as HTMLElement
    node.style.backgroundImage = isGradient ? source : cssUrl(source)
    node.classList.toggle("ken", ken)
    applyView(view, nxt)
    void nxt.offsetWidth
    nxt.classList.add("on")
    if (animate) cur.classList.remove("on")
    else {
      cur.classList.remove("on")
      nxt.style.transition = "none"
      void nxt.offsetWidth
      nxt.style.transition = ""
    }
    side = side === "a" ? "b" : "a"
  }
  if (isGradient) { swap(); return }
  const probe = new Image()
  probe.onload = swap
  probe.onerror = () => { current = null; toast("背景图加载失败") }
  probe.src = source
}

function scheduleBackground() {
  // 常驻图优先：它是全局的一张（跟当前游戏无关），选中就一直用它。
  const pinned = pinnedBackground()
  if (pinned) {
    window.clearTimeout(timer)
    timer = window.setTimeout(() => applyBackground(pinned.url, pinned.view), 140)
    return
  }
  const game = state.games.find((row) => row.id === state.focus)
  if (!game) return
  window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    applyBackground(game.background || fallbackBackground(game), bgViewOf(game))
    const keys = state.games.filter((row) => row.id).map((row) => row.id).concat("__add__")
    const index = Math.max(0, keys.indexOf(String(state.focus)))
    for (const delta of [-1, 1]) {
      const near = state.games.find((row) => row.id === keys[ringMod(index + delta, keys.length)])
      if (near?.background) { const img = new Image(); img.src = near.background }
    }
  }, 140)
}

/** 设置里的「常驻背景图」：只在 mode=custom 且确实有图时生效。 */
function pinnedBackground(): { url: string; view: { scale: number; x: number; y: number } } | null {
  if (String(state.settings.background_mode || "game") !== "custom") return null
  // 后端存的是 `assets/…`（相对页面），v2 的页面在 /v2/ 下会解析错 —— 统一补成 /assets/…
  const url = fixAssetUrl(String(state.settings.background_custom || ""))
  if (!url) return null
  const scale = Math.max(1, Math.min(3, Number(state.settings.background_custom_scale) || 1))
  return { url, view: { scale, x: 0, y: 0 } }
}

function applyKenBurns(on: boolean) {
  inner()?.classList.toggle("ken", !!on)
}

onMounted(() => {
  onUi("background", scheduleBackground)
  onUi("library:loaded", scheduleBackground)
  onUi("settings:applied", scheduleBackground)
})
onUnmounted(() => {
  window.clearTimeout(timer)
  window.clearTimeout(viewTimer)
})

defineExpose({ scheduleBackground, applyBackground, applyKenBurns, fallbackBackground,
               pinnedBackground })

// 焦点是背景的输入：自己盯着它，别指望每个改焦点的调用方都记得通知一次
// （启动时 refreshLibrary 先于焦点恢复，只靠事件会漏掉第一张壁纸）
watch(() => state.focus, () => scheduleBackground())
</script>
