<template>
  <div id="vntextPanel" class="sheet glass wide" data-slot="sheet" data-nodrag :class="{ open: state.panels.vntext }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3>游戏内翻译</h3>
        <span id="vnSub" class="sub">把游戏里的日文台词实时翻成简体中文</span>
      </div>
      <button id="vnClose" class="icon-btn" type="button" @click="state.panels.vntext = false">✕</button>
    </div>

    <div class="set-actions">
      <button id="vnToggle" class="btn glass-btn" type="button" @click="toggleRun">
        <span>{{ running ? "停止翻译" : "开启翻译" }}</span>
      </button>
      <button id="vnPush" class="btn glass-btn" type="button" @click="toggleOverlay">
        <span>{{ overlayOn ? "隐藏悬浮窗" : "显示悬浮窗" }}</span>
      </button>
      <button id="vnRetry" class="btn glass-btn" type="button" @click="retryLast"><span>重译最后一句</span></button>
      <button id="vnPause" class="btn glass-btn" type="button" @click="togglePause">
        <span>{{ paused ? "继续" : "暂停" }}</span>
      </button>
      <button id="vnThrough" class="btn glass-btn" type="button" @click="toggleThrough">
        <span>{{ through ? "取消穿透" : "切换穿透" }}</span>
      </button>
    </div>
    <p id="vnState" class="set-note">{{ stateText }}</p>
    <div id="vnThreads" class="vn-threads">
      <button
        v-for="thread in threads"
        :key="thread.id"
        class="vn-thread"
        :class="{ on: thread.active }"
        type="button"
        @click="lockThread(thread.id)"
      >
        {{ thread.name || `线程 ${thread.id}` }}<small>{{ thread.lines ?? 0 }}</small>
      </button>
    </div>

    <div class="set-actions">
      <input id="vnHook" v-model="hookCode" type="text" placeholder="例如 HQ-4@A22E:AdvHD_crack.exe" spellcheck="false">
      <button id="vnHookSend" class="mini-btn" type="button" @click="sendHook">发送</button>
      <button id="vnHookSave" class="mini-btn" type="button" @click="saveHook">存为专用</button>
    </div>
    <p id="vnHookNote" class="set-note">{{ hookNote }}</p>

    <div class="set-actions">
      <button id="vnFind" class="mini-btn" type="button" @click="startFind">找不到文本？开始侦测</button>
      <button id="vnFindStop" class="mini-btn" type="button" @click="stopFind">中止</button>
      <button id="vnAdvance" class="mini-btn" type="button" @click="advance">翻一页</button>
    </div>
    <div class="set-row">
      <input id="vnFindText" v-model="findText" type="text" placeholder="留空＝自动 OCR 识别当前台词" spellcheck="false">
      <span />
    </div>
    <p id="vnFindNote" class="set-note">{{ findNote }}</p>
    <div id="vnFindCands" class="vn-threads">
      <button
        v-for="row in candidates"
        :key="row.code"
        class="vn-thread"
        :class="{ on: row.active }"
        type="button"
        @click="applyHook(row)"
      >{{ row.code }}<small>{{ row.score ?? "" }}</small></button>
    </div>

    <div class="set-actions">
      <button id="vnFraming" class="mini-btn" type="button" @click="openFrame">框选区域…</button>
      <span id="vnRegion" class="hint">{{ regionText }}</span>
    </div>

    <div id="vnHistory" class="vn-history">
      <div v-for="(row, index) in history" :key="index" class="vn-row">
        <i>{{ row.provider || "—" }}</i>
        <span>{{ row.translation || row.text }}</span>
        <span v-if="row.fallback_from" class="vn-fb">插件未响应，已兜底 {{ row.fallback_from }}</span>
      </div>
      <div v-if="!history.length" class="list-empty">还没有台词。开启翻译后这里会实时显示。</div>
    </div>
  </div>

  <!-- OCR 框选 -->
  <div id="frameBox" class="frame-box" :hidden="!framing">
    <div class="frame-head">
      <b>框选台词区域</b>
      <span id="frameHint">建议只框住台词区域，别把按钮和标题栏框进来</span>
      <button id="frameCancel" class="btn glass-btn" type="button" @click="framing = false">取消</button>
      <button id="frameOk" class="btn primary" type="button" @click="confirmFrame">确定</button>
    </div>
    <div id="frameStage" class="frame-stage" ref="stage" @mousedown="startSelect">
      <img id="frameImg" :src="frameImage" alt="" @load="onFrameLoad">
      <div id="frameSel" class="frame-sel" :hidden="!selection.w" :style="selectionStyle" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import { call } from "@/core/api"
import { onUi, emitUi } from "@/core/bus"
import { currentGame, state, toast } from "@/core/store"
import { contextBridge } from "./bridge-shim"

const running = ref(false)
const paused = ref(false)
const through = ref(false)
const overlayOn = ref(false)
const stateText = ref("—")
const hookCode = ref("")
const hookNote = ref("—")
const findText = ref("")
const findNote = ref("Textractor 抓不到文本时：Aurora 会自己盯住这句台词的内存。")
const threads = ref<any[]>([])
const candidates = ref<any[]>([])
const history = ref<any[]>([])
const regionText = ref("未框选，默认全屏识别")
const framing = ref(false)
const frameImage = ref("")
const stage = ref<HTMLElement>()
const selection = ref({ x: 0, y: 0, w: 0, h: 0 })
let frameSize = { w: 1, h: 1 }
let drag: { x: number; y: number } | null = null

const selectionStyle = computed(() => ({
  left: `${selection.value.x}px`,
  top: `${selection.value.y}px`,
  width: `${selection.value.w}px`,
  height: `${selection.value.h}px`,
}))

const ENGINE_LABEL: Record<string, string> = {
  auto: "自动", hook: "Textractor 钩子", textractor: "Textractor 钩子", ocr: "OCR",
}

function applyStatus(payload: any): void {
  state.vntext = payload || {}
  running.value = !!payload?.running
  paused.value = !!payload?.paused
  through.value = !!(payload?.overlay?.click_through ?? payload?.click_through)
  overlayOn.value = !!(payload?.overlay_open ?? payload?.overlay)
  threads.value = payload?.threads || []
  candidates.value = payload?.candidates || candidates.value
  hookCode.value = payload?.game_hook || payload?.hook_code || hookCode.value
  const engine = String(payload?.engine || payload?.mode || "")
  const engineLabel = ENGINE_LABEL[engine] || engine
  const bits: string[] = []
  if (payload?.locked_thread != null) bits.push(`锁定线程 ${payload.locked_thread}`)
  if (payload?.hook_skip) bits.push(String(payload.hook_skip))
  // 判据（tools/e2e.py）：运行中时 #vnState 里必须有「正在翻译」
  const head = running.value ? `正在翻译${engineLabel ? `（${engineLabel}）` : ""}` : "未在翻译"
  stateText.value = [head, ...bits].join(" · ")
  regionText.value = payload?.region
    ? `已框选 ${Math.round(payload.region.width)}×${Math.round(payload.region.height)}`
    : "未框选，默认全屏识别"
}

async function refresh(): Promise<void> {
  try {
    applyStatus(await call("get_vntext_status"))
  } catch { /* 离线忽略 */ }
}

async function toggleRun(): Promise<void> {
  const game = currentGame()
  if (!game) return
  if (running.value) {
    await call("stop_vntext")
    toast("已停止翻译")
  } else {
    const res = await call("start_vntext", game.id)
    toast(res?.ok === false ? "启动失败：" + (res.error || "") : "已开始翻译")
  }
  await refresh()
}
async function toggleOverlay(): Promise<void> {
  const res = await call("toggle_overlay")
  overlayOn.value = !!res?.visible
}
async function retryLast(): Promise<void> {
  const row = history.value[0]
  if (!row?.text) { toast("还没有可重译的台词"); return }
  await call("translate_line_now", row.text)
  toast("已重新翻译")
}
async function togglePause(): Promise<void> {
  paused.value = !paused.value
  await call("set_vntext_paused", paused.value)
}
async function toggleThrough(): Promise<void> {
  through.value = !through.value
  await call("set_overlay_click_through", through.value)
}
async function lockThread(id: number): Promise<void> {
  await call("lock_vntext_thread", id)
  await refresh()
}
async function sendHook(): Promise<void> {
  if (!hookCode.value.trim()) return
  const res = await call("send_hook_code", hookCode.value.trim())
  hookNote.value = res?.ok === false ? `发送失败：${res.error}` : "已发送到正在运行的 Textractor"
}
async function saveHook(): Promise<void> {
  const game = currentGame()
  if (!game || !hookCode.value.trim()) return
  const res = await call("set_vntext_hook", game.id, hookCode.value.trim())
  hookNote.value = res?.ok === false ? `保存失败：${res.error}` : "已存为这款游戏的专用钩子码"
}
async function startFind(): Promise<void> {
  const game = currentGame()
  if (!game) return
  findNote.value = "已开始侦测：翻一页游戏，让它吐出下一句台词…"
  const res = await call("start_hook_search", game.id, findText.value.trim() || null)
  if (res?.ok === false) findNote.value = "启动失败：" + (res.error || "")
}
async function stopFind(): Promise<void> {
  await call("stop_hook_search")
  findNote.value = "已中止侦找。"
}
async function advance(): Promise<void> {
  const game = currentGame()
  if (!game) return
  await call("advance_game", game.id)
}
async function applyHook(row: any): Promise<void> {
  const game = currentGame()
  if (!game) return
  await call("set_vntext_hook", game.id, row.code)
  await call("send_hook_code", row.code)
  hookNote.value = `已应用 ${row.code}`
  toast("已应用钩子码")
}

async function openFrame(): Promise<void> {
  const game = currentGame()
  if (!game) return
  const res = await call("capture_game_frame", game.id)
  if (!res || !res.ok) { toast("截屏失败：" + ((res && res.error) || "")); return }
  frameImage.value = res.image
  selection.value = { x: 0, y: 0, w: 0, h: 0 }
  framing.value = true
}
function onFrameLoad(event: Event): void {
  const img = event.target as HTMLImageElement
  frameSize = { w: img.clientWidth || 1, h: img.clientHeight || 1 }
}
function startSelect(event: MouseEvent): void {
  const rect = (stage.value as HTMLElement).getBoundingClientRect()
  drag = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  const move = (moveEvent: MouseEvent) => {
    if (!drag) return
    const x = moveEvent.clientX - rect.left
    const y = moveEvent.clientY - rect.top
    selection.value = {
      x: Math.min(drag.x, x), y: Math.min(drag.y, y),
      w: Math.abs(x - drag.x), h: Math.abs(y - drag.y),
    }
  }
  const up = () => {
    drag = null
    document.removeEventListener("mousemove", move)
    document.removeEventListener("mouseup", up)
  }
  document.addEventListener("mousemove", move)
  document.addEventListener("mouseup", up)
}
async function confirmFrame(): Promise<void> {
  const game = currentGame()
  if (!game || selection.value.w < 6 || selection.value.h < 6) { framing.value = false; return }
  const sx = frameSize.w / (stage.value?.clientWidth || 1)
  const sy = frameSize.h / (stage.value?.clientHeight || 1)
  await call("set_vntext_region", game.id, {
    x: Math.round(selection.value.x * sx),
    y: Math.round(selection.value.y * sy),
    width: Math.round(selection.value.w * sx),
    height: Math.round(selection.value.h * sy),
  })
  framing.value = false
  toast("已保存框选区域")
  await refresh()
}

onMounted(() => {
  onUi("vntext:open", () => {
    state.panels.vntext = true
    void refresh()
  })
  onUi("vntext:status", (payload: any) => applyStatus(payload))
  onUi("vntext:line", (payload: any) => {
    if (payload?.phase === "translated" || payload?.phase === "source") {
      history.value = [payload, ...history.value].slice(0, 40)
    }
  })
  onUi("hooksearch:status", (payload: any) => {
    if (payload?.message) findNote.value = payload.message
    if (Array.isArray(payload?.candidates)) candidates.value = payload.candidates
    if (payload?.code) hookCode.value = payload.code
  })
})
defineExpose({ refresh, applyStatus })
void contextBridge
void emitUi
</script>
