<template>
  <!-- 资料源管理 -->
  <div id="sourcePanel" class="sheet glass wide" data-slot="sheet" data-nodrag :class="{ open: state.panels.source }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3>资料源</h3>
        <span class="sub">从上到下依次尝试，命中即用</span>
      </div>
      <button id="sourceClose" class="icon-btn" type="button" @click="state.panels.source = false">✕</button>
    </div>
    <div id="sourceList" class="source-list">
      <div v-for="(row, index) in state.sources" :key="row.id" class="steam-row">
        <input class="switch sm" type="checkbox" :checked="row.enabled !== false"
               :disabled="row.builtin" @change="toggleSource(row, $event)">
        <div class="steam-body">
          <div class="steam-name">
            {{ row.name }}
            <span class="src-badge">{{ row.kind === "link" ? "跳转" : (row.kind || "接口") }}</span>
            <span v-if="row.plugin" class="src-badge">插件</span>
            <span v-if="row.builtin" class="src-badge">内置</span>
          </div>
          <div class="steam-meta">{{ row.detail || row.url || "" }}</div>
        </div>
        <button class="mini-btn" type="button" :data-source-test="row.id" @click="testSource(row)">测试</button>
        <button class="mini-btn" type="button" :data-source-up="row.id" :disabled="index === 0"
                @click="moveSource(row, -1)">↑</button>
        <button class="mini-btn" type="button" :data-source-down="row.id" :disabled="index === state.sources.length - 1"
                @click="moveSource(row, 1)">↓</button>
        <button class="mini-btn" type="button" :data-source-del="row.id" :disabled="row.builtin"
                @click="removeSource(row)">✕</button>
      </div>
    </div>
    <div id="sourceForm" class="source-form" :hidden="!showForm">
      <div class="set-row"><label for="srcName">名称</label>
        <input id="srcName" v-model="form.name" type="text" placeholder="例如 我的资料站" spellcheck="false"><span /></div>
      <div class="set-row"><label for="srcKind">类型</label>
        <select id="srcKind" v-model="form.kind">
          <option value="api">接口源（返回 JSON）</option>
          <option value="link">跳转源（只用浏览器打开）</option>
        </select><span /></div>
      <div class="set-row"><label for="srcUrl">地址</label>
        <input id="srcUrl" v-model="form.url" type="text"
               placeholder="https://example.com/api/search?q={query}" spellcheck="false"><span /></div>
      <div id="srcApiFields" :hidden="form.kind !== 'api'">
        <div class="set-row"><label for="srcResults">结果路径</label>
          <input id="srcResults" v-model="form.results" type="text"
                 placeholder="data.list（留空表示整个响应就是列表）" spellcheck="false"><span /></div>
        <div class="set-row"><label for="srcFields">字段映射</label>
          <textarea id="srcFields" v-model="form.fields" rows="5" spellcheck="false"
                    placeholder='{"id":"id","name":"name_cn||name","description":"summary","cover":"images.large"}' /><span /></div>
      </div>
      <div class="set-actions">
        <button id="srcCancel" class="btn glass-btn" type="button" @click="showForm = false">取消</button>
        <button id="srcSave" class="btn primary" type="button" @click="saveSource">保存并测试</button>
      </div>
    </div>
    <div class="sheet-foot">
      <button id="srcAdd" class="btn glass-btn full" type="button" @click="showForm = true">+ 添加自定义源</button>
    </div>
  </div>

  <!-- Steam 扫描 -->
  <div id="steamPanel" class="sheet glass wide" data-slot="sheet" data-nodrag :class="{ open: state.panels.steam }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3>从 Steam 导入</h3>
        <span id="steamSub" class="sub">读取本机 Steam 清单，导入时直接按 appid 取资料</span>
      </div>
      <button id="steamClose" class="icon-btn" type="button" @click="state.panels.steam = false">✕</button>
    </div>
    <div class="steam-tools">
      <button id="steamAll" class="mini-btn" type="button" @click="selectAllSteam(true)">全选</button>
      <button id="steamNone" class="mini-btn" type="button" @click="selectAllSteam(false)">全不选</button>
      <span id="steamPickHint" class="hint">{{ steamPicked.size ? `已选 ${steamPicked.size} 个` : "" }}</span>
    </div>
    <div id="steamList" class="steam-list">
      <div v-if="!steam.length" class="list-empty">正在读取 Steam 库…</div>
      <div v-for="row in steam" :key="row.appid" class="steam-row" :class="{ off: row.imported }"
           @click="toggleSteam(row)">
        <input class="switch sm" type="checkbox" :checked="steamPicked.has(row.appid)" :disabled="row.imported">
        <div class="steam-body">
          <div class="steam-name">{{ row.name }}<span v-if="row.imported" class="src-badge">已导入</span></div>
          <div class="steam-meta">{{ row.appid }} · {{ row.dir || "" }}</div>
        </div>
      </div>
    </div>
    <div class="sheet-foot">
      <button id="steamImport" class="btn primary full" type="button" :disabled="!steamPicked.size"
              @click="importSteam">导入选中的游戏</button>
    </div>
  </div>

  <!-- 获取游戏 -->
  <div id="getPanel" class="sheet glass wide" data-slot="sheet" data-nodrag :class="{ open: state.panels.get }">
    <div class="sheet-head" data-slot="sheet-head">
      <div>
        <h3>获取游戏</h3>
        <span class="sub">打开资源站下载，下载完自动导入</span>
      </div>
      <button id="getClose" class="icon-btn" type="button" @click="state.panels.get = false">✕</button>
    </div>
    <div class="get-search">
      <input id="getQuery" v-model="getQuery" type="text"
             placeholder="关键词（可选；站点地址里带 {query} 时会用它去搜索）" spellcheck="false">
    </div>
    <div class="get-chips" id="getSites">
      <span v-for="row in state.sites" :key="row.id" class="link-chip site-chip" :data-site="row.id">
        <button type="button" class="site-open" @click="openSite(row)">{{ row.name }}</button>
        <button type="button" class="site-del" title="删除站点" aria-label="删除站点" @click.stop="removeSite(row)">
          <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" /></svg>
        </button>
      </span>
      <button id="getAddSite" class="mini-btn" type="button" @click="showSiteForm = !showSiteForm">＋ 添加站点</button>
    </div>
    <div id="getSiteForm" class="source-form" :hidden="!showSiteForm">
      <div class="set-row"><label for="getSiteName">名称</label>
        <input id="getSiteName" v-model="siteForm.name" type="text" placeholder="例如 TouchGal" spellcheck="false"><span /></div>
      <div class="set-row"><label for="getSiteUrl">地址</label>
        <input id="getSiteUrl" v-model="siteForm.url" type="text"
               placeholder="https://example.com/search?query={query}" spellcheck="false"><span /></div>
      <div class="set-actions">
        <button id="getSiteCancel" class="btn glass-btn" type="button" @click="showSiteForm = false">取消</button>
        <button id="getSiteSave" class="btn primary" type="button" @click="saveSite">保存</button>
      </div>
    </div>
    <div class="get-block">
      <div class="get-row-line">
        <span class="get-label">下载目录</span>
        <span id="getDir" class="get-path">{{ download.dir || "—" }}</span>
        <button id="getChangeDir" class="mini-btn" type="button" @click="pickDir">选择…</button>
        <button id="getOpenDir" class="mini-btn" type="button" @click="openDir">打开</button>
      </div>
      <div class="get-row-line">
        <label class="get-toggle">
          <input id="getWatch" v-model="download.watch" class="switch sm" type="checkbox" @change="saveDownload('watch', download.watch)">
          <span>自动导入</span>
        </label>
        <label class="get-toggle">
          <input id="getExtract" v-model="download.extract" class="switch sm" type="checkbox" @change="saveDownload('extract', download.extract)">
          <span>自动解压</span>
        </label>
        <button id="getScan" class="mini-btn" type="button" @click="scanNow">立即扫描</button>
        <span id="getDirHint" class="get-hint">{{ dirHint }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue"
import { domValue } from "@/core/dom"

import { call } from "@/core/api"
import { emitUi, onUi } from "@/core/bus"
import { refreshLibrary } from "@/core/actions"
import { state, toast } from "@/core/store"

const showForm = ref(false)
const showSiteForm = ref(false)
const form = reactive({ name: "", kind: "api", url: "", results: "", fields: "" })
const siteForm = reactive({ name: "", url: "" })
const steam = ref<any[]>([])
const steamPicked = ref(new Set<number>())
const getQuery = ref("")
const dirHint = ref("")
const download = reactive({ dir: "", watch: true, extract: false })

async function refreshSources(): Promise<void> {
  try {
    const payload = await call("list_sources")
    state.sources = payload?.sources || payload || []
  } catch { /* 离线保留现有 */ }
}
async function saveSource(): Promise<void> {
  // 以 DOM 为准：探针会直接写 .value（不触发 input 事件）
  const name = domValue("srcName", form.name.trim())
  const kind = domValue("srcKind", form.kind)
  const url = domValue("srcUrl", form.url.trim())
  const results = domValue("srcResults", form.results)
  const rawFields = domValue("srcFields", form.fields)
  if (!name || !url) { toast("名称和地址都要填"); return }
  let fields: Record<string, string> = {}
  if (kind === "api" && rawFields) {
    try { fields = JSON.parse(rawFields) } catch { toast("字段映射不是合法 JSON"); return }
  }
  const res = await call("add_custom_source", {
    name,
    kind,
    url,
    results,
    fields,
  })
  if (!res || res.ok === false) { toast("保存失败：" + ((res && res.error) || "")); return }
  showForm.value = false
  form.name = ""
  form.url = ""
  form.fields = ""
  await refreshSources()
  toast("已保存自定义源")
  if (res.source?.id) {
    const tested = await call("test_source", res.source.id)
    toast(tested?.ok ? `测试通过：${tested.count ?? 0} 条结果` : `测试失败：${(tested && tested.error) || ""}`)
  }
}
async function toggleSource(row: any, event: Event): Promise<void> {
  const value = (event.target as HTMLInputElement).checked
  await call("toggle_source", row.id, value)
  row.enabled = value
}
async function moveSource(row: any, delta: number): Promise<void> {
  const index = state.sources.findIndex((item) => item.id === row.id)
  const target = index + delta
  if (target < 0 || target >= state.sources.length) return
  await call("move_source", row.id, delta)
  await refreshSources()
}
async function removeSource(row: any): Promise<void> {
  await call("remove_custom_source", row.id)
  await refreshSources()
  toast("已删除自定义源")
}
async function testSource(row: any): Promise<void> {
  const res = await call("test_source", row.id)
  toast(res?.ok ? `可用：${res.count ?? 0} 条结果` : `不可用：${(res && res.error) || ""}`, 3600)
}

async function scanSteam(): Promise<void> {
  steam.value = []
  try {
    const res = await call("scan_steam")
    steam.value = res?.items || []
  } catch (error) {
    toast("扫描失败：" + (error as Error).message)
  }
}
function selectAllSteam(on: boolean): void {
  const next = new Set<number>()
  if (on) for (const row of steam.value) if (!row.imported) next.add(row.appid)
  steamPicked.value = next
}
function toggleSteam(row: any): void {
  if (row.imported) return
  const next = new Set(steamPicked.value)
  if (next.has(row.appid)) next.delete(row.appid)
  else next.add(row.appid)
  steamPicked.value = next
}
async function importSteam(): Promise<void> {
  const items = steam.value.filter((row) => steamPicked.value.has(row.appid))
  if (!items.length) return
  state.batch = { kind: "steam", done: 0, total: items.length }
  const res = await call("import_steam_games", items)
  if (!res || !res.ok) {
    state.batch = null
    toast("导入失败：" + ((res && res.error) || ""))
    return
  }
  toast(`开始导入 ${items.length} 个游戏`)
}

async function refreshDownload(): Promise<void> {
  try {
    const res = await call("get_download_settings")
    download.dir = res?.dir || ""
    download.watch = res?.watch !== false
    download.extract = !!res?.extract
  } catch { /* 离线忽略 */ }
}
async function saveDownload(key: string, value: unknown): Promise<void> {
  await call("set_download_option", key, value)
  dirHint.value = key === "watch" ? (value ? "已开启自动导入" : "已关闭自动导入") : ""
}
async function pickDir(): Promise<void> {
  const res = await call("pick_download_dir")
  if (!res || res.cancelled) return
  download.dir = res.dir || download.dir
  toast("已更新下载目录")
}
function openDir(): void { void call("open_download_dir") }
async function scanNow(): Promise<void> {
  const res = await call("scan_downloads")
  toast(res?.count ? `发现 ${res.count} 个游戏，已导入` : "下载目录里没有新的游戏", 3600)
  await refreshLibrary()
}
async function refreshSites(): Promise<void> {
  try {
    const res = await call("list_sites")
    state.sites = res?.sites || []
  } catch { /* 离线忽略 */ }
}
function openSite(row: any): void {
  void call("open_site", row.id, getQuery.value.trim() || null)
}
async function removeSite(row: any): Promise<void> {
  await call("remove_site", row.id)
  await refreshSites()
  toast("已删除站点")
}
async function saveSite(): Promise<void> {
  const name = domValue("getSiteName", siteForm.name.trim())
  const url = domValue("getSiteUrl", siteForm.url.trim())
  if (!name || !url) { toast("名称和地址都要填"); return }
  const res = await call("add_site", name, url)
  if (!res || res.ok === false) { toast("保存失败：" + ((res && res.error) || "")); return }
  siteForm.name = ""
  siteForm.url = ""
  showSiteForm.value = false
  await refreshSites()
  toast("已添加站点")
}

onMounted(() => {
  onUi("source:open", () => { state.panels.source = true; void refreshSources() })
  onUi("steam:open", () => { state.panels.steam = true; void scanSteam() })
  onUi("get:open", () => {
    state.panels.get = true
    void refreshDownload()
    void refreshSites()
  })
  onUi("steam:done", () => { void scanSteam() })
})
</script>
