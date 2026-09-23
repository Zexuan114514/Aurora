<template>
  <section id="categoriesView" :hidden="hidden">
    <div class="cat-body">
      <aside class="cat-nav glass" data-slot="nav">
        <nav id="catRoots" class="cat-list">
          <button class="cat-item" data-slot="nav-row" :class="{ on: state.scope.type === 'all' }" data-scope="all" @click="pickScope('all', '')">
            <span>全部游戏</span><small>{{ state.shelfStats.total ?? state.games.length }}</small>
          </button>
          <button class="cat-item" data-slot="nav-row" :class="{ on: state.scope.type === 'unfiled' }" data-scope="unfiled" @click="pickScope('unfiled', '')">
            <span>未分类</span><small>{{ unfiledCount }}</small>
          </button>
          <button class="cat-item" data-slot="nav-row" :class="{ on: state.scope.type === 'fav' }" data-scope="fav" @click="pickScope('fav', '')">
            <span>已收藏</span><small>{{ favoriteCount }}</small>
          </button>
        </nav>

        <div class="cat-label" data-slot="nav-label"><span>自定义分类</span>
          <button id="catNew" class="cat-add" type="button" title="新建分类" @click="showCreate = true">＋</button>
        </div>
        <form id="catCreate" class="cat-create" :hidden="!showCreate" @submit.prevent="submitShelf">
          <input id="catName" v-model="newShelfName" type="text" maxlength="24"
                 placeholder="分类名称，例如：悬疑推理" spellcheck="false">
          <div class="cat-create-foot">
            <button id="catCancel" class="btn glass-btn" type="button" @click="cancelCreate">取消</button>
            <button id="catSave" class="btn primary" type="submit">创建</button>
          </div>
          <p id="catHint" class="cat-hint">{{ catHint }}</p>
        </form>
        <nav id="catShelves" class="cat-list">
          <div v-if="!state.shelves.length" class="cat-hint" style="color: var(--text-3)">
            还没有分类，点右上角 ＋ 新建一个。
          </div>
          <div v-for="(shelf, index) in state.shelves" :key="shelf.id" class="cat-row"
               :class="{ on: state.scope.type === 'shelf' && state.scope.value === shelf.id }">
            <button class="cat-item" data-slot="nav-row" :class="{ on: state.scope.type === 'shelf' && state.scope.value === shelf.id }"
                    data-scope="shelf" :data-id="shelf.id" @click="pickScope('shelf', shelf.id)">
              <span>{{ shelf.name }}</span><small>{{ shelf.count ?? 0 }}</small>
            </button>
            <span class="cat-ops">
              <button type="button" title="上移" :disabled="index === 0" @click="moveShelf(shelf.id, -1)">↑</button>
              <button type="button" title="下移" :disabled="index === state.shelves.length - 1" @click="moveShelf(shelf.id, 1)">↓</button>
              <button type="button" title="重命名" @click="renameShelf(shelf.id)">✎</button>
              <button type="button" class="danger" title="删除分类" @click="deleteShelf(shelf.id)">✕</button>
            </span>
          </div>
        </nav>

        <div class="cat-label" data-slot="nav-label"><span>按状态</span></div>
        <nav id="catStatusList" class="cat-list">
          <button v-for="value in STATUS_ORDER" :key="value || 'none'" class="cat-item" data-slot="nav-row"
                  :class="{ on: state.scope.type === 'status' && state.scope.value === value }"
                  data-scope="status" :data-id="value" @click="pickScope('status', value)">
            <span>{{ STATUS_LABEL[value] }}</span>
            <small>{{ state.games.filter((g) => (g.status || '') === value).length }}</small>
          </button>
        </nav>

        <div class="cat-label" data-slot="nav-label"><span>按开发商</span></div>
        <nav id="catDevs" class="cat-list">
          <button v-for="row in devRows" :key="row.name" class="cat-item" data-slot="nav-row"
                  :class="{ on: state.scope.type === 'dev' && state.scope.value === row.name }"
                  data-scope="dev" :data-id="row.name" @click="pickScope('dev', row.name)">
            <span>{{ row.name }}</span><small>{{ row.count }}</small>
          </button>
          <button v-if="devTotal > DEV_LIMIT" class="cat-item" data-slot="nav-row" type="button" data-dev-more="1"
                  @click="state.devExpand = !state.devExpand">
            <span>{{ state.devExpand ? "收起" : `更多（${devTotal - DEV_LIMIT}）` }}</span>
          </button>
        </nav>
      </aside>

      <section class="cat-main glass" data-slot="card">
        <div class="cat-head">
          <div class="cat-title">
            <h2 id="catTitle" data-slot="section-title">{{ scopeName() }}</h2>
            <span id="catSub" class="sub" data-slot="section-sub">{{ catSub }}</span>
          </div>
          <div id="catActions" class="cat-actions">
            <button class="mini-btn" :class="{ on: state.organizing }" type="button" data-cat="organize"
                    @click="state.organizing = !state.organizing; state.selected.clear()">
              {{ state.organizing ? "完成整理" : "批量归类" }}
            </button>
            <template v-if="isShelfScope && !state.organizing">
              <button class="mini-btn" type="button" data-cat="rename" @click="renameShelf(state.scope.value)">重命名</button>
              <button class="mini-btn" type="button" data-cat="delete" @click="deleteShelf(state.scope.value)">删除分类</button>
            </template>
          </div>
        </div>

        <div class="cat-tools">
          <div class="cat-search">
            <svg viewBox="0 0 24 24" class="ic"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
            <input id="catQuery" v-model="state.filter" type="search" placeholder="在分类里搜索游戏"
                   autocomplete="off" spellcheck="false" @input="syncSearch">
          </div>
          <select id="catSort" v-model="state.sort" title="排序方式" @change="syncSort">
            <option value="default">默认顺序</option>
            <option value="favorite">收藏优先</option>
            <option value="name">按名称</option>
            <option value="recent">最近游玩</option>
            <option value="playtime">游玩时长</option>
          </select>
        </div>

        <div id="catWall" class="cat-wall">
          <div v-if="!visible.length" class="cat-empty">
            {{ state.filter.trim() ? "这个范围里没有匹配的游戏。" : "这个范围里还没有游戏。" }}
          </div>
          <button v-for="game in visible" :key="game.id" class="cat-card" data-slot="tile"
                  :class="{ on: state.selected.has(game.id) }" :data-id="game.id" :title="game.name"
                  @click="onCard(game)">
            <span class="cat-art" data-slot="cover-art">
              <b>{{ String(game.name || "?").trim().charAt(0).toUpperCase() }}</b>
              <img v-if="coverOf(game)" :src="coverOf(game)" alt="" loading="lazy">
              <i v-if="state.organizing" class="cat-mark">{{ state.selected.has(game.id) ? "✓" : "" }}</i>
            </span>
            <span class="cat-name" data-slot="tile-title">{{ game.name }}</span>
            <span class="cat-dev" data-slot="tile-meta">{{ (game.developers || [])[0] || STATUS_LABEL[game.status || ""] || "" }}</span>
          </button>
        </div>

        <div id="catBar" class="cat-bar" data-slot="bar" :hidden="!state.organizing">
          <b>已选 {{ state.selected.size }} 部</b>
          <button class="mini-btn" type="button" data-catbar="all" @click="selectAll">全选当前结果</button>
          <button class="mini-btn" type="button" data-catbar="none" @click="state.selected.clear()">清空</button>
          <select id="catTarget" v-model="target">
            <option value="">选择目标分类</option>
            <option v-for="shelf in state.shelves" :key="shelf.id" :value="shelf.id">{{ shelf.name }}</option>
          </select>
          <button class="mini-btn" type="button" data-catbar="add" @click="assign">加入分类</button>
          <button v-if="isShelfScope" class="mini-btn" type="button" data-catbar="remove" @click="removeFromShelf">移出当前分类</button>
          <button class="mini-btn" type="button" data-catbar="fav" @click="favorite(true)">收藏</button>
          <button class="mini-btn" type="button" data-catbar="unfav" @click="favorite(false)">取消收藏</button>
          <span class="hint">点封面勾选</span>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import { call } from "@/core/api"
import { onUi, emitUi } from "@/core/bus"
import { runtime } from "@/core/app"
import { domValue } from "@/core/dom"
import { modal } from "@/core/modal"
import { replaceShelves, state, toast } from "@/core/store"
import { STATUS_LABEL, STATUS_ORDER, inScope, scopeCount, scopeName, searchHit, sortGames } from "@/core/query"

const props = defineProps<{ hidden: boolean }>()
const DEV_LIMIT = 12

const showCreate = ref(false)
const newShelfName = ref("")
const catHint = ref("")
const target = ref("")

const unfiledCount = computed(() =>
  state.shelfStats.unfiled ?? state.games.filter((g) => !(g.bookshelf_ids || []).length).length)
const favoriteCount = computed(() => state.games.filter((g) => g.favorite).length)
const isShelfScope = computed(() => state.scope.type === "shelf" && !!state.scope.value)

const list = computed(() => {
  let rows = state.games.filter((game) => inScope(game))
  const q = state.filter.trim().toLowerCase()
  if (q) rows = rows.filter((game) => searchHit(game, q))
  return sortGames(rows.slice())
})
const visible = computed(() => list.value)
const catSub = computed(() => `${list.value.length} 部`
  + (state.filter.trim() ? `（筛选自 ${scopeCount()} 部）` : ""))

const devs = computed(() => {
  const counts = new Map<string, number>()
  for (const game of state.games) {
    for (const dev of game.developers || []) if (dev) counts.set(dev, (counts.get(dev) || 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh"))
})
const devTotal = computed(() => devs.value.length)
const devRows = computed(() => (state.devExpand ? devs.value : devs.value.slice(0, DEV_LIMIT))
  .map(([name, count]) => ({ name, count })))

function coverOf(game: any): string {
  return game.custom_cover || game.cover || (game.cover_sources || [])[0] || game.header_image || ""
}

function applyPayload(res: any): void {
  if (!res) return
  if (Array.isArray(res.shelves)) replaceShelves(res.shelves)
  if (typeof res.unfiled === "number") {
    state.shelfStats = { unfiled: res.unfiled, total: res.total ?? state.games.length }
  }
  if (Array.isArray(res.games)) {
    for (const row of res.games) {
      const index = state.games.findIndex((game) => game.id === row.id)
      if (index >= 0) state.games[index] = { ...state.games[index], ...row }
    }
  }
  if (res.removed) {
    for (const game of state.games) {
      game.bookshelf_ids = (game.bookshelf_ids || []).filter((id: string) => id !== res.removed)
    }
  }
  emitUi("render")
}

async function refreshShelves(): Promise<void> {
  try {
    applyPayload(await call("list_shelves"))
  } catch { /* 离线时保留现有状态 */ }
}

function pickScope(type: string, value: string): void {
  state.scope = type && type !== "all" ? { type, value: value || "" } : { type: "all", value: "" }
  state.selected.clear()
  try { localStorage.setItem("aurora.scope", JSON.stringify(state.scope)) } catch { /* ignore */ }
  const rows = list.value
  if (!rows.some((game) => game.id === state.focus)) state.focus = rows[0]?.id || "__add__"
  emitUi("render")
  runtime.ring?.update()
}

function syncSearch(): void {
  const box = document.getElementById("searchInput") as HTMLInputElement | null
  if (box && box.value !== state.filter) box.value = state.filter
  emitUi("render")
}
function syncSort(): void {
  emitUi("render")
}
function onCard(game: any): void {
  if (state.organizing) {
    if (state.selected.has(game.id)) state.selected.delete(game.id)
    else state.selected.add(game.id)
    return
  }
  state.focus = game.id
  emitUi("render")
  emitUi("detail:open")
}
function selectAll(): void {
  state.selected = new Set(list.value.map((game) => game.id))
}

async function submitShelf(): Promise<void> {
  // 探针会直接写 .value 再点保存（不触发 input 事件），所以以 DOM 为准
  const name = domValue("catName", newShelfName.value.trim())
  const res = await call("create_shelf", name)
  if (!res || !res.ok) {
    catHint.value = res && res.error === "duplicate" ? "已经有同名的分类了"
      : (res && res.error === "too-long" ? "名字太长了（最多 24 字）" : "名字不能为空")
    return
  }
  catHint.value = ""
  showCreate.value = false
  newShelfName.value = ""
  applyPayload(res)
  toast(`已新建分类「${res.shelf.name}」`)
  pickScope("shelf", res.shelf.id)
}
function cancelCreate(): void {
  showCreate.value = false
  catHint.value = ""
}
async function renameShelf(id: string): Promise<void> {
  const shelf = state.shelves.find((row) => row.id === id)
  if (!shelf) return
  const value = await modal({
    title: "重命名分类", body: "只改分类名字，不动里面的游戏。",
    input: true, value: shelf.name, okText: "保存",
  })
  if (value === null) return
  const res = await call("rename_shelf", id, value)
  if (!res || !res.ok) {
    toast(res && res.error === "duplicate" ? "已经有同名的分类了" : "名字不能为空")
    return
  }
  applyPayload(res)
  toast("已重命名分类")
}
async function deleteShelf(id: string): Promise<void> {
  const shelf = state.shelves.find((row) => row.id === id)
  if (!shelf) return
  const ok = await modal({
    title: "删除分类",
    body: `删除「${shelf.name}」？游戏和游玩记录都不会动，只是不再归在这个分类里。`,
    okText: "删除",
  })
  if (!ok) return
  applyPayload(await call("delete_shelf", id))
  if (state.scope.type === "shelf" && state.scope.value === id) pickScope("all", "")
  toast("已删除分类")
}
async function moveShelf(id: string, delta: number): Promise<void> {
  const res = await call("move_shelf", id, delta)
  if (res && res.ok) applyPayload(res)
}
async function assign(): Promise<void> {
  const ids = [...state.selected]
  if (!ids.length) { toast("先勾选几张封面"); return }
  const shelfId = domValue("catTarget", target.value)
  if (!shelfId) { toast("先在下拉里选一个目标分类"); return }
  const res = await call("add_games_to_shelf", ids, [shelfId])
  state.selected.clear()
  applyPayload(res)
  const shelf = state.shelves.find((row) => row.id === shelfId)
  toast(`已把 ${res?.count || 0} 部加入「${shelf ? shelf.name : "分类"}」`)
}
async function removeFromShelf(): Promise<void> {
  const ids = [...state.selected]
  if (!isShelfScope.value || !ids.length) return
  const res = await call("remove_games_from_shelf", ids, state.scope.value)
  state.selected.clear()
  applyPayload(res)
  toast(`已移出 ${res?.count || 0} 部`)
}
async function favorite(value: boolean): Promise<void> {
  const ids = [...state.selected]
  if (!ids.length) { toast("先勾选几张封面"); return }
  const res = await call("set_games_favorite", ids, value)
  toast(value ? `已收藏 ${res?.count || 0} 部` : `已取消收藏 ${res?.count || 0} 部`)
  applyPayload(res)
}

onMounted(() => {
  onUi("shelves:refresh", () => { void refreshShelves() })
  onUi("library:loaded", () => { void refreshShelves() })
})
defineExpose({ refreshShelves, pickScope })
</script>
