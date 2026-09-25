<template>
  <header id="toolbar" class="glass" data-drag data-slot="toolbar">
    <div class="brand" data-slot="brand">
      <b>Aurora</b>
      <span>游戏启动器</span>
    </div>
    <div class="search" data-slot="search" :style="state.settingsOpen ? { display: 'none' } : undefined">
      <svg viewBox="0 0 24 24" class="ic"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
      <input
        id="searchInput"
        v-model="state.filter"
        type="search"
        placeholder="搜索游戏库"
        autocomplete="off"
        spellcheck="false"
        @input="onSearch"
        @keydown.enter="onSearchEnter"
      >
      <button id="searchClear" class="clear" type="button" :hidden="!state.filter" @click="clearSearch">✕</button>
    </div>
    <!-- 右侧一列：搜索之后所有控件都贴到窗口右边，窗口按钮在最外侧 -->
    <div class="toolbar-right">
      <el-tooltip content="排序方式" placement="bottom" :show-after="420">
        <button id="btnSort" class="icon-btn" type="button" aria-label="排序方式" @click.stop="toggleSort">
          <svg viewBox="0 0 24 24" class="ic"><path d="M4 7h16M6 12h12M9 17h6" /></svg>
        </button>
      </el-tooltip>
      <div id="viewSwitch" class="view-switch" data-slot="switch">
        <button class="vs-btn" type="button" data-view="home" :class="{ on: state.view === 'home' }"
                :disabled="state.settingsOpen" @click="switchView('home')">主页</button>
        <button class="vs-btn" type="button" data-view="categories" :class="{ on: state.view === 'categories' }"
                :disabled="state.settingsOpen" @click="switchView('categories')">分类</button>
      </div>
      <el-tooltip content="设置（再点一次收起）" placement="bottom" :show-after="420">
        <button
          id="btnSettings"
          class="icon-btn"
          type="button"
          aria-label="设置"
          :class="{ on: state.settingsOpen }"
          @click="toggleSettings"
        >
          <svg viewBox="0 0 24 24" class="ic">
            <circle cx="12" cy="12" r="3.2" />
            <path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
          </svg>
        </button>
      </el-tooltip>

      <!-- 大厅的两个入口（原来是压在画面左上角的胶囊）：仅图标 + 悬停说明。
           只在主页显示；分类 / 游戏页 / 设置页收起来（那时它们说的不是当前页面）。 -->
      <el-tooltip content="获取游戏（下载大厅）" placement="bottom" :show-after="420">
        <button
          id="btnGetGames"
          class="icon-btn get-pill"
          type="button"
          aria-label="获取游戏"
          :hidden="!hallActions"
          @click="openGet"
        >
          <svg viewBox="0 0 24 24" class="ic"><path d="M12 4v10m0 0 4-4m-4 4-4-4M5 19h14" /></svg>
        </button>
      </el-tooltip>
      <el-tooltip :content="'浏览范围：' + scopeLabel" placement="bottom" :show-after="420">
        <div id="scopePill" class="icon-btn scope-pill" :hidden="!hallActions">
          <button
            id="scopePick"
            class="scope-main"
            type="button"
            aria-label="浏览范围"
            @click="toggleScopeMenu"
          >
            <svg viewBox="0 0 24 24" class="ic"><path d="M4 7h16M4 12h10M4 17h6" /></svg>
            <!-- 只给探针与读屏用：视觉上是纯图标按钮（见 tools/e2e.py 的判据） -->
            <span id="scopeLabel" class="sr-only">{{ scopeLabel }}</span>
          </button>
          <button
            id="scopeClear"
            class="scope-clear"
            type="button"
            aria-label="清除筛选，显示全部"
            :hidden="state.scope.type === 'all'"
            @click="clearScope"
          >×</button>
        </div>
      </el-tooltip>

      <div class="win-btns" data-slot="win">
        <el-tooltip content="最小化" placement="bottom" :show-after="420">
          <button id="btnMin" class="wbtn" type="button" aria-label="最小化">
            <svg viewBox="0 0 12 12"><path d="M2 6h8" /></svg>
          </button>
        </el-tooltip>
        <el-tooltip content="最大化 / 还原" placement="bottom" :show-after="420">
          <button id="btnMax" class="wbtn" type="button" aria-label="最大化">
            <svg viewBox="0 0 12 12"><rect x="2.5" y="2.5" width="7" height="7" rx="1" /></svg>
          </button>
        </el-tooltip>
        <el-tooltip content="关闭" placement="bottom" :show-after="420">
          <button id="btnClose" class="wbtn wclose" type="button" aria-label="关闭">
            <svg viewBox="0 0 12 12"><path d="M3 3l6 6M9 3l-6 6" /></svg>
          </button>
        </el-tooltip>
      </div>
    </div>
  </header>

  <!-- 排序菜单 -->
  <div id="sortMenu" class="menu glass" data-nodrag :hidden="!state.menus.sort">
    <button
      v-for="row in SORTS"
      :key="row.value"
      type="button"
      :data-sort="row.value"
      :class="{ on: state.sort === row.value }"
      @click="pickSort(row.value)"
    >{{ row.label }}</button>
  </div>

  <!-- 作用域菜单 -->
  <div id="scopeMenu" class="menu glass scope-menu" data-nodrag :hidden="!state.menus.scope">
    <div class="scope-group">范围</div>
    <button
      v-for="row in scopeRows"
      :key="row.type + row.value"
      type="button"
      :class="{ on: state.scope.type === row.type && (state.scope.value || '') === (row.value || '') }"
      :data-scope-type="row.type"
      :data-scope-value="row.value"
      @click="pickScope(row.type, row.value)"
    ><span>{{ row.label }}</span><small>{{ row.count }}</small></button>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"

import { emitUi } from "@/core/bus"
import { closeSettings, openSettings, setView } from "@/core/app"
import { state } from "@/core/store"
import { STATUS_LABEL, STATUS_ORDER, scopeCount, scopeName, visibleGames } from "@/core/query"
import { runtime } from "@/core/app"

const SORTS = [
  { value: "default", label: "默认顺序" },
  { value: "favorite", label: "收藏优先" },
  { value: "name", label: "按名称" },
  { value: "recent", label: "最近游玩" },
  { value: "playtime", label: "游玩时长" },
]

const scopeRows = computed(() => {
  const rows: { type: string; value: string; label: string; count: number }[] = [
    { type: "all", value: "", label: "全部游戏", count: state.games.length },
    {
      type: "unfiled", value: "", label: "未分类",
      count: state.shelfStats.unfiled ?? state.games.filter((g) => !(g.bookshelf_ids || []).length).length,
    },
    { type: "fav", value: "", label: "已收藏", count: state.games.filter((g) => g.favorite).length },
  ]
  for (const shelf of state.shelves) {
    rows.push({ type: "shelf", value: shelf.id, label: shelf.name, count: shelf.count ?? 0 })
  }
  for (const value of STATUS_ORDER) {
    rows.push({
      type: "status", value, label: STATUS_LABEL[value],
      count: state.games.filter((game) => (game.status || "") === value).length,
    })
  }
  const devs = new Map<string, number>()
  for (const game of state.games) {
    for (const dev of game.developers || []) if (dev) devs.set(dev, (devs.get(dev) || 0) + 1)
  }
  for (const [name, count] of [...devs.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh")).slice(0, 12)) {
    rows.push({ type: "dev", value: name, label: name, count })
  }
  return rows
})

/** 大厅的两个入口（获取游戏 / 浏览范围）只在主页、且大厅真的在显示时有意义。 */
const hallActions = computed(() => !state.settingsOpen && state.view === "home"
  && state.page !== "game" && state.games.length > 0)
const scopeLabel = computed(() => `${scopeName()} · ${scopeCount()}`)

/** 菜单贴着触发它的按钮：右缘对齐、压在按钮下方（窗口太窄时夹回可视区）。 */
function placeMenu(menuId: string, anchorId: string, gap = 10): void {
  const menu = document.getElementById(menuId)
  const anchor = document.getElementById(anchorId)
  if (!menu || !anchor) return
  const rect = anchor.getBoundingClientRect()
  const width = menu.offsetWidth || 208
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width))
  menu.style.left = `${Math.round(left)}px`
  menu.style.right = "auto"
  menu.style.top = `${Math.round(rect.bottom + gap)}px`
}

function onSearch(): void {
  const box = document.getElementById("catQuery") as HTMLInputElement | null
  if (box && box.value !== state.filter) box.value = state.filter
  emitUi("render")
}
function clearSearch(): void {
  state.filter = ""
  emitUi("render")
}
function onSearchEnter(): void {
  const first = visibleGames()[0]
  if (!first) return
  emitUi("focus", first.id)
  emitUi("open-game", first.id)
}
function toggleSort(): void {
  const next = !state.menus.sort
  state.menus.scope = false
  state.menus.more = false
  state.menus.sort = next
  if (next) requestAnimationFrame(() => placeMenu("sortMenu", "btnSort"))
}
function pickSort(value: string): void {
  state.sort = value
  state.menus.sort = false
  emitUi("render")
  if (state.focus) emitUi("focus", state.focus)
}
function toggleScopeMenu(): void {
  const next = !state.menus.scope
  state.menus.sort = false
  state.menus.more = false
  state.menus.scope = next
  if (next) requestAnimationFrame(() => placeMenu("scopeMenu", "scopePick"))
}
function openGet(): void {
  state.menus.scope = false
  state.menus.sort = false
  emitUi("get:open")
}
function clearScope(): void {
  state.menus.scope = false
  state.scope = { type: "all", value: "" }
  try { localStorage.setItem("aurora.scope", JSON.stringify(state.scope)) } catch { /* ignore */ }
  const games = visibleGames()
  if (!games.some((game) => game.id === state.focus)) state.focus = games[0]?.id || "__add__"
  emitUi("render")
  runtime.ring?.update()
}
function pickScope(type: string, value: string): void {
  state.menus.scope = false
  state.scope = type && type !== "all" ? { type, value: value || "" } : { type: "all", value: "" }
  state.selected.clear()
  try { localStorage.setItem("aurora.scope", JSON.stringify(state.scope)) } catch { /* ignore */ }
  const games = visibleGames()
  if (!games.some((game) => game.id === state.focus)) state.focus = games[0]?.id || "__add__"
  emitUi("render")
  runtime.ring?.update()
}
function switchView(view: "home" | "categories"): void {
  setView(view)
  if (view === "categories") emitUi("shelves:refresh")
}
function toggleSettings(): void {
  if (state.settingsOpen) closeSettings()
  else openSettings()
}

defineExpose({ pickScope })
</script>
