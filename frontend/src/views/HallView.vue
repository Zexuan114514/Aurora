<template>
  <section id="hall" :class="{ 'hall-list': layout === 'list' }" :hidden="hidden">
    <!-- 默认布局：大图 + 侧列表 -->
    <div v-if="layout === 'list'" class="hall-list-body">
      <div class="hall-hero" data-slot="hero">
        <div class="hall-hero-art" data-slot="cover" @click="enterGame(state.focus || undefined)">
          <b>{{ initial }}</b>
          <img v-if="focusCover" :src="focusCover" :data-srcs="coverChain" alt="">
        </div>
        <div class="hall-label" data-slot="hero-label">
          <div class="label-rule" data-slot="rule" />
          <h1 data-slot="title">{{ heroName }}</h1>
          <div class="hall-label-meta" data-slot="meta">{{ heroMeta }}</div>
          <p class="hall-label-desc" data-slot="desc">{{ heroDesc }}</p>
          <!-- 19-a：主页直接启动（原先靠双击封面 —— 反馈第 18 条把那条删了） -->
          <div class="hall-label-actions" data-slot="hero-actions">
            <button
              id="btnHallPlay"
              class="btn play"
              type="button"
              :disabled="!state.focus"
              @click="playGame(state.focus || undefined)"
            >启动游戏</button>
          </div>
        </div>
      </div>
      <aside class="hall-side glass" data-slot="card">
        <div class="hall-side-head"><span>全部游戏</span><span>{{ rows.length }} 部</span></div>
        <div id="hallSideRows" ref="sideRows" class="hall-side-rows">
          <button
            v-for="game in rows"
            :key="game.id"
            class="hall-row-item"
            :class="{ on: game.id === state.focus }"
            data-slot="row"
            type="button"
            :data-id="game.id"
            @click="setFocus(game.id)"
          >
            <img :src="game.custom_cover || game.cover || game.header_image || ''" alt="" loading="lazy">
            <span>
              <span class="row-title">{{ game.name }}</span>
              <span class="row-meta">{{ rowMeta(game) }}</span>
            </span>
            <span class="row-time" data-slot="row-time">{{ rowTime(game) }}</span>
          </button>
          <button class="hall-row-item" data-slot="row" type="button" title="导入本地游戏" @click="importGames">
            <img src="" alt="">
            <span>
              <span class="row-title">导入游戏</span>
              <span class="row-meta">选择一个 .exe / .bat</span>
            </span>
            <span class="row-time">＋</span>
          </button>
        </div>
      </aside>
    </div>

    <!-- 环形队列 / 平铺横滑：v1 那套 DOM 与几何，判据逐字不变 -->
    <div id="hallViewport" ref="viewport" class="hall-viewport">
      <div id="hallRow" ref="row" class="hall-ring">
          <button
            v-for="key in keys"
            :key="key"
            class="gi"
            data-slot="tile"
          :class="{ focus: key === state.focus, 'gi-add': key === ADD_KEY, searching: isBusy(key) }"
          :data-id="key === ADD_KEY ? undefined : key"
          :data-add="key === ADD_KEY ? '1' : undefined"
          :title="titleOf(key)"
          type="button"
        >
          <span class="gi-card" data-slot="cover">
            <template v-if="key === ADD_KEY">
              <svg viewBox="0 0 24 24" class="ic"><path d="M12 5v14M5 12h14" /></svg>
              <span>导入游戏</span>
              <span class="gi-ring" />
            </template>
            <template v-else>
              <span class="gi-cover" data-slot="cover-art">
                <img
                  v-if="coverOf(key)"
                  :src="coverOf(key)"
                  :data-srcs="chainOf(key)"
                  alt=""
                  loading="lazy"
                  decoding="async"
                >
                <b>{{ initialOf(key) }}</b>
              </span>
              <span class="veil" />
              <span v-if="badgesOf(key).length" class="gi-badges">
                <span
                  v-for="badge in badgesOf(key)"
                  :key="badge.text"
                  class="gi-badge"
                  :class="badge.cls"
                  :title="badge.title"
                >{{ badge.text }}</span>
              </span>
              <span class="gi-ring" data-slot="cover-frame" />
            </template>
          </span>
        </button>
      </div>
    </div>

    <div id="hallFoot" class="hall-foot" data-drag data-slot="rail">
      <div class="hall-info">
        <div id="hallName" class="hall-name" data-slot="rail-title">{{ heroName }}</div>
        <div id="hallSub" class="hall-sub" data-slot="rail-sub">{{ heroSub }}</div>
      </div>
      <div class="hall-hint" data-slot="rail-hint">
        <span id="hallCount">{{ countText }}</span>
        <span><b>← →</b> 切换 &nbsp; <b>Enter</b> 进入 &nbsp; <b>Ctrl+F</b> 搜索</span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue"

import { emitUi, onUi } from "@/core/bus"
import { enterGame, hallKeys, playGame, runtime, setFocus } from "@/core/app"
import { importGames } from "@/core/actions"
import { ADD_KEY, currentGame, state } from "@/core/store"
import { STATUS_GLYPH, STATUS_LABEL, visibleGames } from "@/core/query"
import { hours } from "@/core/time"
import { createRing } from "@/features/hall/ring"

const props = defineProps<{ hidden: boolean }>()

const row = ref<HTMLElement>()
const sideRows = ref<HTMLElement>()
const viewport = ref<HTMLElement>()
const tick = ref(0)

const layout = computed(() => {
  const value = String(state.settings.hall_layout || "list")
  return value === "ring" || value === "flat" ? value : "list"
})
/** 空库时不排任何一格（v1 的 renderHall 也是直接 return；判据要求 .gi 数为 0）。 */
const keys = computed(() => (state.games.length ? hallKeys() : []))
const rows = computed(() => visibleGames())

const focusGame = computed(() => currentGame())
const heroName = computed(() => focusGame.value?.name || "导入游戏")
const heroSub = computed(() => {
  const game = focusGame.value
  if (!game) return "选择一个 .exe / .bat，或把游戏文件夹拖进窗口"
  const bits: string[] = [
    (game.developers || [])[0],
    (game.release_date || "").match(/\d{4}/)?.[0],
  ].filter(Boolean) as string[]
  if ((game.genres || [])[0]) bits.push(String((game.genres || [])[0]))
  if ((game.play_time || 0) > 0) bits.push(`已玩 ${hours(game.play_time || 0)}`)
  if (game.running) bits.push("运行中")
  return bits.join(" · ") || String(game.exe_name || "")
})
const heroMeta = computed(() => heroSub.value)
const heroDesc = computed(() => {
  const game = focusGame.value
  if (!game) return ""
  return game.description || game.description_translated || game.about || ""
})
const focusCover = computed(() => coverOf(String(state.focus)))
const coverChain = computed(() => chainOf(String(state.focus)))
const initial = computed(() => (heroName.value || "?").trim().charAt(0).toUpperCase())
const countText = computed(() => {
  const filtered = state.filter.trim()
  return filtered
    ? `匹配 ${visibleGames().length} / 共 ${state.games.length} 个游戏`
    : `共 ${state.games.length} 个游戏`
})

function gameOf(key: string) {
  return state.games.find((game) => game.id === key)
}
function coverSources(game: any): string[] {
  const list: string[] = []
  const push = (url?: string) => { if (url && !list.includes(url)) list.push(url) }
  if (game.custom_cover) push(game.custom_cover)
  const sources: string[] = (game.cover_sources || []).slice()
  sources.filter((url) => /600x900_2x/.test(url)).forEach(push)
  sources.filter((url) => !/600x900_2x/.test(url)).forEach(push)
  push(game.cover)
  push(game.header_image)
  push(game.custom_icon)
  return list
}
function coverOf(key: string): string {
  const game = gameOf(key)
  if (!game) return ""
  return coverSources(game)[0] || ""
}
function chainOf(key: string): string {
  const rest = coverSources(gameOf(key) || ({} as any)).slice(1)
  return rest.length ? JSON.stringify(rest) : ""
}
function initialOf(key: string): string {
  const game = gameOf(key)
  return game ? String(game.name || "?").trim().charAt(0).toUpperCase() : ""
}
function isBusy(key: string): boolean {
  const game = gameOf(key)
  return !!game && (game.metadata_state === "searching" || !!state.busy[game.id])
}
function titleOf(key: string): string {
  return key === ADD_KEY ? "导入游戏" : (gameOf(key)?.name || "")
}
function badgesOf(key: string) {
  const game = gameOf(key)
  if (!game) return []
  const out: { text: string; cls: string; title?: string }[] = []
  if (game.running) out.push({ text: "●", cls: "run" })
  if (game.favorite) out.push({ text: "★", cls: "fav" })
  if (game.locale_enabled) out.push({ text: "JP", cls: "loc" })
  if (game.status && STATUS_GLYPH[game.status]) {
    out.push({ text: STATUS_GLYPH[game.status], cls: `st-${game.status}`, title: STATUS_LABEL[game.status] })
  }
  if (game.missing) out.push({ text: "!", cls: "warn" })
  else if (game.metadata_state === "notfound") out.push({ text: "?", cls: "warn" })
  return out
}
function rowMeta(game: any): string {
  const bits = [(game.developers || [])[0], (game.release_date || "").match(/\d{4}/)?.[0]]
  return bits.filter(Boolean).join(" · ") || String(game.exe_name || "")
}
function rowTime(game: any): string {
  if ((game.play_time || 0) > 0) return hours(game.play_time)
  if (game.running) return "运行中"
  return "未开始"
}

const ring = createRing({
  keys: () => hallKeys(),
  onFocus: (key, opts) => setFocus(key, opts),
  onEnter: (id) => enterGame(id),
  onPlay: (id) => playGame(id),
  // 「＋ 导入游戏」那一格直接进本地导入（使用者 2026-09-23 的意见：不再二选一，
  // 「获取游戏」是顶部栏那个按钮的事）。见 docs/frontend-ux-feedback.md 第 5 条。
  onAdd: () => { void importGames() },
}, ADD_KEY)

onMounted(async () => {
  await nextTick()
  if (row.value && viewport.value) {
    ring.attach(row.value, viewport.value)
    runtime.ring = ring
    const app = document.getElementById("app")
    if (app) ring.bind(app)
    ring.applyLayout()
  }
  onUi("render", () => {
    tick.value++
    nextTick(() => ring.update())
  })
  onUi("tick", () => { tick.value++ })
  onUi("focus", (id: string) => setFocus(id))
  onUi("layout:apply", () => ring.applyLayout())
})
onUnmounted(() => { runtime.ring = undefined })

// 键列表变化（导入 / 筛选 / 排序）后重新摆位
watch(() => keys.value.join("|"), () => {
  nextTick(() => ring.update())
})
watch(layout, () => { nextTick(() => ring.applyLayout()) })
watch(() => state.focus, () => { nextTick(() => ring.update()) })

// 「大图 + 侧列表」：滚轮 / 方向键切当前游戏之后，把那一行滚进可视区
// （右侧栏跟着当前游戏动 —— 使用者 2026-09-23 的意见）
watch(() => [state.focus, layout.value], () => {
  nextTick(() => {
    if (layout.value !== "list") return
    const active = sideRows.value?.querySelector(".hall-row-item.on") as HTMLElement | null
    active?.scrollIntoView({ block: "nearest" })
  })
}, { immediate: true })

defineExpose({ ring })
</script>
