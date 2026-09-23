<template>
  <!-- 背景图 -->
  <div id="bgPanel" class="sheet glass" data-slot="sheet" data-nodrag :class="{ open: state.panels.background }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3>背景图</h3>
        <span id="bgCount" class="sub">{{ (game?.images || []).length ? `共 ${(game?.images || []).length} 张可选` : "暂无可选图片" }}</span>
      </div>
      <button id="bgClose" class="icon-btn" type="button" @click="state.panels.background = false">✕</button>
    </div>
    <!-- 背景来源：默认跟随当前游戏；切到常驻图就是全局的一张（只支持一张） -->
    <div id="bgSource" class="chips">
      <button id="bgModeGame" class="chip" :class="{ accent: !pinned }" type="button"
              @click="setBackgroundMode('game')">背景 · 跟随当前游戏</button>
      <button id="bgModeCustom" class="chip" :class="{ accent: pinned }" type="button"
              @click="setBackgroundMode('custom')">背景 · 常驻图</button>
    </div>
    <p id="bgSourceHint" class="set-note">{{ bgSourceHint }}</p>
    <div id="bgGrid" class="bg-grid">
      <div v-if="!(game?.images || []).length" class="list-empty" style="grid-column: 1/-1">
        {{ game?.metadata_state === "ok" ? "该游戏没有可用图片，试试从本地选择。" : "还没有获取到图片，先完成游戏信息搜索。" }}
      </div>
      <button
        v-for="image in game?.images || []"
        :key="image.url"
        class="bg-item" data-slot="thumb"
        :class="{ active: image.url === game?.background }"
        type="button"
        :data-url="image.url"
        :data-kind="image.kind"
        :title="image.label || ''"
        @click="chooseBackground(image)"
      >
        <span class="bg-thumb">
          <img :src="image.thumb || image.url" alt="">
          <i>无法预览</i>
        </span>
        <span class="bg-label" data-slot="thumb-label">{{ image.label || "" }}</span>
      </button>
    </div>
    <div class="sheet-foot">
      <div class="set-row" v-if="pinned">
        <label>常驻图</label>
        <button id="bgPickPinned" class="mini-btn" type="button" @click="pickPinned">更换图片…</button>
        <button id="bgClearPinned" class="mini-btn" type="button" @click="clearPinned">清除</button>
        <span />
      </div>
      <div class="set-row">
        <label for="bgZoom">{{ pinned ? "常驻图缩放" : "缩放" }}</label>
        <input id="bgZoom" type="range" min="100" max="300" step="1" :value="zoom"
               @input="onZoom" @change="commitZoom">
        <span id="bgZoomVal">{{ zoom }}%</span>
        <button id="bgViewReset" class="mini-btn" type="button" @click="resetView">复位</button>
      </div>
      <button id="btnLocalBg" class="btn glass-btn full" type="button" @click="pickLocal">
        <span>从本地选择图片…</span>
      </button>
      <button id="btnResetBg" class="btn glass-btn full" type="button" @click="resetBackground">
        <span>恢复默认</span>
      </button>
    </div>
  </div>

  <!-- 换封面 -->
  <div id="coverPanel" class="sheet glass" data-slot="sheet" data-nodrag :class="{ open: state.panels.cover }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3>更换封面</h3>
        <span class="sub">点一张即应用</span>
      </div>
      <button id="coverClose" class="icon-btn" type="button" @click="state.panels.cover = false">✕</button>
    </div>
    <div id="coverGrid" class="bg-grid">
      <div v-if="!covers.length" class="list-empty" style="grid-column: 1/-1">
        还没有可用图片，可以先用「从本地选择图片」。
      </div>
      <button
        v-for="row in covers"
        :key="row.url"
        class="bg-item" data-slot="thumb"
        :class="{ active: row.url === game?.custom_cover }"
        type="button"
        :data-cover="row.url"
        :title="row.label"
        @click="applyCover(row.url)"
      >
        <span class="bg-thumb"><img :src="row.url" alt=""><i>无法预览</i></span>
        <span class="bg-label" data-slot="thumb-label">{{ row.label }}</span>
      </button>
    </div>
    <div class="sheet-foot">
      <button id="btnLocalCover" class="btn glass-btn full" type="button" @click="pickLocalCover">从本地选择图片…</button>
      <button id="btnCoverReset" class="btn glass-btn full" type="button" @click="resetCover">恢复默认封面</button>
    </div>
  </div>

  <!-- 详情 -->
  <div id="detailPanel" class="sheet glass wide" data-slot="sheet" data-nodrag :class="{ open: state.panels.detail }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3 id="dTitle">{{ game?.name || "详情" }}</h3>
        <span id="dSub" class="sub">{{ detailSub }}</span>
      </div>
      <button id="detailClose" class="icon-btn" type="button" @click="state.panels.detail = false">✕</button>
    </div>
    <div id="detailBody" class="detail-body">
      <p>{{ detailText }}</p>
      <h4>详细信息</h4>
      <dl class="kv">
        <template v-for="row in detailRows" :key="row.label">
          <dt>{{ row.label }}</dt>
          <dd v-html="row.html" />
        </template>
      </dl>
      <div class="set-row" style="margin-top: 10px">
        <label for="detailStatus">游玩状态</label>
        <select
          id="detailStatus"
          :value="game?.status || ''"
          @change="saveStatus(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="value in STATUS_ORDER" :key="value || 'none'" :value="value">
            {{ STATUS_LABEL[value] }}
          </option>
        </select>
        <span />
      </div>
      <template v-if="(game?.sessions || []).length">
        <h4>游玩记录 <span class="hint">启动 {{ game?.play_count || 0 }} 次</span></h4>
        <div class="session-list">
          <div v-for="row in recentSessions" :key="row.started_at" class="session-row">
            <span>{{ stamp(row.started_at) }}</span><b>{{ clock(row.seconds) }}</b>
          </div>
        </div>
      </template>
      <template v-if="shots.length">
        <h4>截图 <span class="hint">点一张可设为背景</span></h4>
        <div class="shot-grid">
          <button v-for="shot in shots" :key="shot.url" class="shot" type="button"
                  :data-shot="shot.url" :data-kind="shot.kind || 'screenshot'"
                  :title="shot.label || ''" @click="chooseBackground(shot)">
            <img :src="shot.thumb || shot.url" alt=""><i>{{ shot.label || "" }}</i>
          </button>
        </div>
      </template>
    </div>
  </div>

  <!-- 手动匹配 -->
  <div id="matchPanel" class="sheet glass wide" data-slot="sheet" data-nodrag :class="{ open: state.panels.match }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3>手动匹配</h3>
        <span class="sub">选择一条候选，按它重新抓取资料</span>
      </div>
      <button id="matchClose" class="icon-btn" type="button" @click="state.panels.match = false">✕</button>
    </div>
    <div class="match-search">
      <input id="matchQuery" v-model="matchQuery" type="text"
             placeholder="例如 千恋万花 / サノバウィッチ / Sabbat of the Witch" spellcheck="false">
      <button id="matchRetry" class="btn glass-btn" type="button" :hidden="!matchRetry" @click="doSearch">
        重试
      </button>
      <button id="matchGo" class="btn glass-btn" type="button" @click="doSearch">搜索</button>
    </div>
    <div id="matchHint" class="match-hint">{{ matchHint }}</div>
    <div id="matchQuick" class="match-quick" :hidden="!quick.length">
      <button v-for="row in quick" :key="row" class="quick-chip" type="button" :data-q="row"
              @click="matchQuery = row; doSearch()">{{ row }}</button>
    </div>
    <div id="matchLinks" class="match-links">
      <button v-for="row in linkSources" :key="row.id" class="link-chip" type="button"
              :data-link-source="row.id" @click="openLinkSource(row)">
        在 {{ row.name }} 搜索
      </button>
    </div>
    <div id="matchList" class="match-list">
      <div v-if="!candidates.length" class="list-empty">
        没有找到候选，换个关键词试试，或检查设置里的资料源。
      </div>
      <button
        v-for="(row, index) in candidates"
        :key="row.source + row.source_id"
        class="match-item"
        :class="{ best: index === 0 && candidates.length > 1 }"
        type="button"
        :data-source="row.source"
        :data-source-id="row.source_id"
        :data-name="row.name"
        @click="applyCandidate(row)"
      >
        <img v-if="row.thumb" :src="row.thumb" alt="" loading="lazy">
        <img v-else alt="">
        <div>
          <div class="mi-name">
            {{ row.name }}
            <span v-if="index === 0 && candidates.length > 1" class="mi-best">匹配度最高</span>
          </div>
          <div class="mi-sub">
            <span class="src-badge">{{ sourceName(row.source) }}</span>
            <span>{{ row.source_id }}</span>
          </div>
        </div>
        <span class="match-score">{{ Math.round((row.score || 0) * 100) }}%</span>
      </button>
    </div>
  </div>

  <!-- 转区启动 -->
  <div id="localePanel" class="sheet glass wide" data-slot="sheet" data-nodrag :class="{ open: state.panels.locale }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3>转区启动</h3>
        <span id="locSub" class="sub">用 Locale Emulator 以日文区域运行这个游戏</span>
      </div>
      <button id="locClose" class="icon-btn" type="button" @click="state.panels.locale = false">✕</button>
    </div>
    <div class="set-row">
      <label for="locSwitch">启用</label>
      <input id="locSwitch" v-model="localeOn" class="switch" type="checkbox" @change="saveLocale">
      <span />
    </div>
    <div class="set-row">
      <label for="locProfile">LE 配置</label>
      <select id="locProfile" v-model="profile" @change="saveLocale">
        <option value="">默认配置</option>
        <option v-for="row in profiles" :key="row.guid" :value="row.guid">{{ row.name || row.guid }}</option>
      </select>
      <span />
    </div>
    <p id="locStatus" class="set-note">{{ localeStatus }}</p>
    <div class="set-actions">
      <button id="locPick" class="btn glass-btn" type="button" @click="pickLe"><span>指定 LEProc.exe…</span></button>
      <button id="locDownload" class="btn glass-btn" type="button" @click="openLe"><span>打开下载页</span></button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import { call } from "@/core/api"
import { applySettings } from "@/core/actions"
import { fixAssetUrl } from "@/core/assets"
import { emitUi, onUi } from "@/core/bus"
import { domValue } from "@/core/dom"
import { modal } from "@/core/modal"
import { currentGame, state, toast } from "@/core/store"
import { clock, hours, sessionSeconds, stamp } from "@/core/time"
import { STATUS_LABEL, STATUS_ORDER } from "@/core/query"

const LE_URL = "https://github.com/xupefei/Locale-Emulator/releases"

const zoom = ref(100)

//: 背景来源：默认跟着当前游戏走，也可以在设置里钉一张常驻图（只支持一张）
const pinned = computed(() => String(state.settings.background_mode || "game") === "custom")
const pinnedUrl = computed(() => String(state.settings.background_custom || ""))
const bgSourceHint = computed(() => pinned.value
  ? (pinnedUrl.value
    ? "常驻图：所有游戏都用这一张（再选一张会替换掉它）。点下面的缩略图会切回「跟随当前游戏」。"
    : "还没有选常驻图，先点「更换图片…」。")
  : (pinnedUrl.value
    ? "跟随当前游戏：切到哪一款就用哪一款的壁纸（已存着一张常驻图，随时可切过去）。"
    : "跟随当前游戏：切到哪一款就用哪一款的壁纸。"))
const matchQuery = ref("")
const matchHint = ref("")
const matchRetry = ref(false)
const candidates = ref<any[]>([])
const quick = ref<string[]>([])
const localeOn = ref(false)
const profile = ref("")
const profiles = ref<any[]>([])
const localeStatus = ref("正在检测 Locale Emulator…")

const game = computed(() => currentGame())
const coverChain = computed(() => [game.value?.custom_cover, game.value?.cover,
  ...(game.value?.cover_sources || []),
  ...((game.value?.images || []).map((row: any) => row.url))])
const covers = computed(() => {
  const out: { url: string; label: string }[] = []
  const seen = new Set<string>()
  const push = (url?: string, label?: string) => {
    if (!url || seen.has(url)) return
    seen.add(url)
    out.push({ url, label: label || "" })
  }
  const row = game.value
  if (!row) return out
  push(row.custom_cover, "当前封面")
  push(row.cover, "默认封面")
  ;(row.cover_sources || []).forEach((url: string) => push(url, "封面候选"))
  ;(row.images || []).forEach((image: any) => push(image.url, image.label || ""))
  return out.slice(0, 24)
})
const shots = computed(() => {
  const list = (game.value?.images || []).filter((row: any) => row.kind === "screenshot")
  return (list.length ? list : (game.value?.images || []).slice(0, 8)).slice(0, 12)
})
const recentSessions = computed(() => (game.value?.sessions || []).slice(-5).reverse())
const detailSub = computed(() => {
  const row = game.value
  if (!row) return ""
  return row.name_original && row.name_original !== row.name ? row.name_original : (row.exe_name || "")
})
const detailText = computed(() => {
  const row = game.value
  if (!row) return ""
  return row.description_translated || row.about || row.description || "暂无简介。"
})
const detailRows = computed(() => {
  const row = game.value
  if (!row) return []
  const rows: { label: string; html: string }[] = []
  const push = (label: string, value?: string) => { if (value) rows.push({ label, html: value }) }
  push("可执行文件", row.exe_name)
  push("所在目录", row.dir)
  push("运行状态", row.running ? `运行中 · PID ${row.play_pid || "-"} · 本次 ${clock(sessionSeconds(row))}` : "")
  push("资料源", sourceName(String(row.data_source || "")))
  push("原名", row.name_original)
  push("开发商", (row.developers || []).join("、"))
  push("发行日期", row.release_date)
  push("类型", (row.genres || []).join("、"))
  push("启动次数", row.play_count ? `${row.play_count} 次` : "")
  push("累计游玩", row.play_time ? hours(row.play_time) : "")
  push("匹配关键词", row.query_used)
  push("启动参数", row.launch_args)
  return rows
})
const linkSources = computed(() => (state.sources || []).filter((row) => row.kind === "link" && row.enabled))

function sourceName(id: string): string {
  const row = (state.sources || []).find((item) => item.id === id)
  return row ? row.name : (id || "")
}

async function chooseBackground(image: any): Promise<void> {
  const row = game.value
  if (!row) return
  // 常驻图模式下点缩略图 = 明确表达「还是跟着游戏走」，先把模式切回来
  if (pinned.value) await setBackgroundMode("game")
  row.background = image.url
  row.background_kind = image.kind
  emitUi("background")
  await call("set_background", row.id, image.url, image.kind)
}

/** 常驻背景：把 bridge 返回的状态写回本地设置，背景层会跟着重画。 */
function acceptBackgroundState(res: any): void {
  applySettings({
    background_mode: res?.mode || "game",
    background_custom: fixAssetUrl(String(res?.url || "")),
    background_custom_scale: Number(res?.scale) || 1,
  })
  zoom.value = Math.round((Number(res?.scale) || 1) * 100)
}
async function setBackgroundMode(mode: "game" | "custom"): Promise<void> {
  const res = await call("set_background_mode", mode)
  if (res && res.ok === false) {
    toast(res.error === "no-image" ? "先选一张常驻图" : "切换背景来源失败")
    return
  }
  acceptBackgroundState(res)
  toast(pinned.value ? "背景：常驻图" : "背景：跟随当前游戏")
}
async function pickPinned(): Promise<void> {
  const res = await call("pick_persistent_background")
  if (!res || res.cancelled) return
  if (!res.ok) { toast("选择失败：" + (res.error || "")); return }
  acceptBackgroundState(res)
  emitUi("background")
  toast("已设为常驻背景图（只保留一张）")
}
async function clearPinned(): Promise<void> {
  const res = await call("clear_persistent_background")
  if (res && res.ok === false) { toast("清除失败：" + (res.error || "")); return }
  acceptBackgroundState(res)
  emitUi("background")
  toast("已清除常驻图，背景跟随当前游戏")
}
function onZoom(event: Event): void {
  const row = game.value
  if (!row) return
  const value = Number((event.target as HTMLInputElement).value) / 100
  zoom.value = Math.round(value * 100)
  if (pinned.value) {
    applySettings({ background_custom_scale: Math.max(1, Math.min(3, value)) })
    emitUi("background")
    return
  }
  row.bg_scale = Math.max(1, Math.min(3, value))
  emitUi("background")
}
/** 松手 / 探针派发 change 时落盘（v1 的口径：input 只预览，change 才持久化）。 */
async function commitZoom(event: Event): Promise<void> {
  const row = game.value
  if (!row) return
  const value = Math.max(1, Math.min(3, Number((event.target as HTMLInputElement).value) / 100))
  zoom.value = Math.round(value * 100)
  if (pinned.value) {
    applySettings({ background_custom_scale: value })
    emitUi("background")
    await call("set_background_custom_scale", value)
    return
  }
  row.bg_scale = value
  emitUi("background")
  await call("set_background_view", row.id, value, 0, 0)
}
async function resetView(): Promise<void> {
  const row = game.value
  if (!row) return
  if (pinned.value) {
    zoom.value = 100
    applySettings({ background_custom_scale: 1 })
    emitUi("background")
    await call("set_background_custom_scale", 1)
    toast("常驻图已复位")
    return
  }
  zoom.value = 100
  row.bg_scale = 1
  emitUi("background")
  await call("set_background_view", row.id, 1, 0, 0)
  toast("背景已复位")
}
async function pickLocal(): Promise<void> {
  const row = game.value
  if (!row) return
  const res = await call("pick_local_background", row.id)
  if (!res || res.cancelled) return
  if (!res.ok) { toast("选择失败：" + (res.error || "")); return }
  Object.assign(row, res.game)
  emitUi("background")
  toast("已应用本地背景图")
}
async function resetBackground(): Promise<void> {
  const row = game.value
  if (!row) return
  const res = await call("clear_background", row.id)
  if (res?.game) Object.assign(row, res.game)
  const first = (row.images || [])[0]
  if (first) { row.background = first.url; row.background_kind = first.kind }
  row.bg_scale = 1
  emitUi("background")
}
async function applyCover(url: string): Promise<void> {
  const row = game.value
  if (!row) return
  const res = await call("set_cover", row.id, url)
  if (res?.game) Object.assign(row, res.game)
  emitUi("render")
  toast("已更换封面")
}
async function pickLocalCover(): Promise<void> {
  const row = game.value
  if (!row) return
  const res = await call("pick_local_cover", row.id)
  if (!res || res.cancelled) return
  if (!res.ok) { toast("选择失败：" + (res.error || "")); return }
  Object.assign(row, res.game)
  emitUi("render")
  toast("已应用本地封面")
}
async function resetCover(): Promise<void> {
  const row = game.value
  if (!row) return
  const res = await call("clear_custom_cover", row.id)
  if (res?.game) Object.assign(row, res.game)
  emitUi("render")
  toast("已恢复默认封面")
}

function fillQuick(): void {
  const row = game.value
  const seen = new Set<string>()
  const out: string[] = []
  const push = (value?: string) => {
    const text = String(value || "").trim()
    if (!text || seen.has(text.toLowerCase())) return
    seen.add(text.toLowerCase())
    out.push(text)
  }
  ;(row?.queries || []).forEach(push)
  push(row?.name_original)
  push(row?.name_cn)
  push(row?.name)
  quick.value = out.slice(0, 5)
}

async function openMatchPanel(payload?: { rows?: any[]; query?: string; note?: string }): Promise<void> {
  const row = game.value
  if (!row) return
  state.panels.match = true
  fillQuick()
  matchQuery.value = payload?.query || row.name || ""
  if (payload?.rows) {
    candidates.value = payload.rows
    matchHint.value = payload.rows.length
      ? `共 ${payload.rows.length} 条候选，按匹配度从高到低排列 —— 点一条就应用。`
      : (payload.note || "没有找到候选：换个写法再搜。")
    matchRetry.value = !payload.rows.length
    return
  }
  candidates.value = []
  matchHint.value = `正在按「${matchQuery.value}」搜索…`
  await doSearch()
}

async function doSearch(): Promise<void> {
  const row = game.value
  if (!row) return
  // 探针会直接写 #matchQuery.value 再点搜索，以 DOM 为准
  const query = domValue("matchQuery", matchQuery.value.trim())
  matchQuery.value = query
  matchHint.value = query ? `正在搜索「${query}」…` : "正在按文件名推断的关键词搜索…"
  try {
    const res = await call("search", row.id, query || null)
    candidates.value = res?.candidates || []
    matchHint.value = candidates.value.length
      ? `共 ${candidates.value.length} 条候选，按匹配度从高到低排列 —— 点一条就应用。`
      : (res?.reason === "network"
        ? "网络不通，没能拿到候选；可以点「重试」再来一次。"
        : "没有找到候选：换个写法（中文名 / 日文原名 / 英文名）再搜。")
    matchRetry.value = !candidates.value.length
  } catch (error) {
    matchHint.value = "搜索出错：" + (error as Error).message
    matchRetry.value = true
  }
}

async function applyCandidate(item: any): Promise<void> {
  const row = game.value
  if (!row || !item) return
  toast("正在获取资料…")
  const res = await call("apply_candidate", row.id, item.source, item.source_id, item.name)
  if (res?.game) Object.assign(row, res.game)
  state.panels.match = false
  emitUi("render")
  toast(res?.ok === false ? "获取失败：" + (res.error || "") : "已应用：" + row.name)
}

function openLinkSource(row: any): void {
  void call("open_source_search", row.id, matchQuery.value.trim() || null)
}

async function refreshLocale(): Promise<void> {
  try {
    const st = await call("get_locale_status")
    profiles.value = st?.profiles || []
    localeStatus.value = st?.available
      ? `已检测到 Locale Emulator：${st.proc}`
      : (st?.proc ? "指定的 LEProc.exe 不可用，请重新选择。" : "未检测到 Locale Emulator。")
  } catch (error) {
    localeStatus.value = "检测失败：" + (error as Error).message
  }
}
async function saveLocale(): Promise<void> {
  const row = game.value
  if (!row) return
  const res = await call("set_game_locale", row.id, localeOn.value, profile.value || undefined)
  if (res?.game) Object.assign(row, res.game)
  emitUi("render")
  toast(localeOn.value ? "已开启转区启动" : "已关闭转区启动")
}
async function pickLe(): Promise<void> {
  const res = await call("pick_locale_proc")
  if (!res || res.cancelled) return
  if (!res.ok) { toast("这个路径不可用：" + (res.error || "")); return }
  await refreshLocale()
  toast("已设置 Locale Emulator 路径")
}
function openLe(): void { void call("open_url", LE_URL) }

async function saveStatus(status: string): Promise<void> {
  const row = game.value
  if (!row) return
  const res = await call("set_game_status", row.id, status)
  if (!res || !res.ok) { toast("保存状态失败"); return }
  if (res.game) Object.assign(row, res.game)
  emitUi("render")
  toast(status ? `已标记为「${STATUS_LABEL[status]}」` : "已清除状态标记")
}

onMounted(() => {
  onUi("candidates", (payload: any) => { void openMatchPanel(payload) })
  onUi("detail:open", () => { state.panels.detail = true })
  onUi("bg:open", () => {
    const row = game.value
    const scale = pinned.value ? Number(state.settings.background_custom_scale) || 1
      : Number(row?.bg_scale) || 1
    zoom.value = Math.round(scale * 100)
    state.panels.background = true
  })
  onUi("cover:open", () => { state.panels.cover = true })
  onUi("locale:open", () => {
    const row = game.value
    localeOn.value = !!row?.locale_enabled
    profile.value = String(row?.locale_guid || "")
    state.panels.locale = true
    void refreshLocale()
  })
  onUi("match:open", () => { void openMatchPanel() })
  void modal
})
</script>
