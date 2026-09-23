<template>
  <div id="card">
    <div id="bar" class="drag pywebview-drag-region">
      <b>Aurora 翻译</b>
      <span id="status">{{ statusText }}</span>
      <span class="grow" />
      <button id="btnMode" type="button" title="切换原文/双语" @click="toggleMode">{{ modeText }}</button>
      <button id="btnPrev" type="button" title="上一句" @click="prev">‹</button>
      <button id="btnNext" type="button" title="下一句" @click="next">›</button>
      <button id="btnCopy" type="button" title="复制译文" @click="copy">复制</button>
      <button id="btnPause" type="button" title="暂停/继续" @click="togglePause">{{ pauseText }}</button>
      <button id="btnThrough" type="button" title="切换鼠标穿透（Ctrl+Alt+T）" @click="toggleThrough">{{ throughText }}</button>
      <button id="btnHide" class="danger" type="button" title="隐藏（Ctrl+Alt+Y）" @click="hide">✕</button>
    </div>
    <div id="notice">{{ notice }}</div>
    <div id="body">
      <div id="source">{{ showSource ? current.source : "" }}</div>
      <div id="trans" :class="{ pending: !current.translation }">{{ transText }}</div>
    </div>
    <div id="hint">Ctrl+Alt+T 切换穿透 · Ctrl+Alt+Y 显示/隐藏 · 拖动右下角缩放</div>
    <div id="grip" title="拖动缩放悬浮窗" @mousedown.stop.prevent="beginResize" />
  </div>
</template>

<script setup lang="ts">
/**
 * 悬浮窗（Vue 版）—— 契约与 v1 的 gl/web/overlay.html 一致：
 *   - 后端通过 `window.vnUpdate(payload)` 推译文（aurora/ui/overlay.py）
 *   - 布局用 id：card / bar / status / btnMode / btnPrev / btnNext / btnCopy /
 *     btnPause / btnThrough / btnHide / notice / body / source / trans / hint / grip
 *     （tools/e2e.py 会读 #trans 的文本）
 *   - 动作名与契约一致：toggle_mode / click_through / pause / hide
 */
import { computed, onMounted, reactive, ref } from "vue"

const bridge = () => (window as any).pywebview?.api
const call = async (name: string, ...args: unknown[]) => {
  const api = bridge()
  if (!api || typeof api[name] !== "function") return null
  try { return await api[name](...args) } catch { return null }
}
const action = (name: string, payload?: unknown) => call("action", name, payload)

const lines = ref<{ source: string; translation: string }[]>([])
const index = ref(-1)
const style = reactive({ mode: "translated", font: 20, opacity: 0.9 })
const clickThrough = ref(true)
const paused = ref(false)
const status = ref("idle")
const notice = ref("")

const current = computed(() => lines.value[index.value] || { source: "", translation: "" })
const showSource = computed(() => style.mode === "bilingual")
const modeText = computed(() => (style.mode === "bilingual" ? "双语" : "仅译文"))
const throughText = computed(() => (clickThrough.value ? "穿透" : "可点"))
const pauseText = computed(() => (paused.value ? "继续" : "暂停"))
const statusText = computed(() => paused.value ? "已暂停"
  : (status.value === "translating" ? "翻译中…"
    : (lines.value.length ? `已翻译 ${lines.value.length} 句` : "未开始")))
const transText = computed(() => current.value.translation
  || (status.value === "translating" ? "翻译中…" : "等待游戏文本…"))

function applyStyle(): void {
  document.documentElement.style.setProperty("--font-size", `${style.font || 20}px`)
  document.documentElement.style.setProperty("--alpha", String(style.opacity ?? 0.9))
}

function update(payload: any): void {
  if (payload?.reset) {
    lines.value = []
    index.value = -1
    notice.value = ""
    status.value = "idle"
  }
  if (payload?.style) Object.assign(style, payload.style)
  if ("clickThrough" in (payload || {})) clickThrough.value = !!payload.clickThrough
  if (payload?.lines) {
    const row = payload.lines
    if (row.source) {
      const found = lines.value.findIndex((item) => item.source === row.source)
      if (found >= 0) {
        if (row.translation) lines.value[found].translation = row.translation
        index.value = found
      } else {
        lines.value.push({ source: row.source, translation: row.translation || "" })
        if (lines.value.length > 60) lines.value.shift()
        index.value = lines.value.length - 1
      }
    } else if (row.translation !== undefined && index.value >= 0) {
      lines.value[index.value].translation = row.translation
    }
    if (row.status) status.value = row.status
  }
  if ("notice" in (payload || {})) notice.value = payload.notice || ""
  if ("paused" in (payload || {})) paused.value = !!payload.paused
  if (payload?.status) status.value = payload.status
  applyStyle()
}

function toggleMode(): void {
  void action("toggle_mode", style.mode === "bilingual" ? "translated" : "bilingual")
}
function toggleThrough(): void { void action("click_through", !clickThrough.value) }
function togglePause(): void { void action("pause", !paused.value) }
function hide(): void { void action("hide", null) }
function prev(): void { if (index.value > 0) index.value -= 1 }
function next(): void { if (index.value < lines.value.length - 1) index.value += 1 }
function copy(): void {
  const row = lines.value[index.value]
  if (row?.translation) void navigator.clipboard?.writeText(row.translation)
}
function beginResize(): void { void call("begin_resize") }

function saveBounds(): void {
  const dpr = window.devicePixelRatio || 1
  void call("save_bounds",
    Math.round(window.screenX * dpr), Math.round(window.screenY * dpr),
    Math.round(window.outerWidth * dpr), Math.round(window.outerHeight * dpr))
}

onMounted(async () => {
  const info = await call("ready")
  if (info?.style) Object.assign(style, info.style)
  if (info && "click_through" in info) clickThrough.value = !!info.click_through
  applyStyle()
  ;(window as any).vnUpdate = update
  let timer: number | undefined
  const save = () => { window.clearTimeout(timer); timer = window.setTimeout(saveBounds, 400) }
  window.addEventListener("mouseup", save)
  window.addEventListener("resize", save)
  window.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") prev()
    if (event.key === "ArrowRight") next()
    if (event.key === "Escape") hide()
  })
})
</script>
