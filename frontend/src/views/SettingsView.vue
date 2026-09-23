<template>
  <section id="settingsView" :hidden="hidden">
    <div class="set-page-head glass" data-slot="page-head">
      <el-button id="setBack" class="btn glass-btn" @click="closeSettings">
        <svg viewBox="0 0 24 24" class="ic"><path d="m14 6-6 6 6 6" /></svg>
        返回
      </el-button>
      <div class="set-title">
        <h2 data-slot="page-title">设置</h2>
        <span id="setVersionLabel" class="sub">v{{ state.version || "—" }}</span>
      </div>
    </div>

    <div class="set-body">
      <nav id="setNav" class="set-nav" data-slot="nav">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          class="set-tab"
          data-slot="nav-row"
          :class="{ on: state.settingsTab === tab.id }"
          type="button"
          :data-pane="tab.id"
          @click="state.settingsTab = tab.id"
        >{{ tab.label }}</button>
      </nav>

      <div class="set-panes" data-slot="surface">
        <!-- 外观 -->
        <div class="set-pane" :class="{ on: state.settingsTab === 'look' }" data-pane="look">
          <h3 data-slot="section-title">外观</h3>
          <div class="set-row">
            <label for="setThemeStyle">风格</label>
            <select id="setThemeStyle" v-model="themeStyle" @change="saveTheme">
              <option v-for="row in THEMES" :key="row.id" :value="row.id">{{ row.name }}</option>
            </select>
            <span />
          </div>
          <p class="set-note" data-slot="note">{{ themeHint }}</p>
          <div class="theme-cards">
            <button
              v-for="row in THEMES"
              :key="row.id"
              type="button"
              class="theme-card" data-slot="theme-card"
              :class="{ on: themeStyle === row.id }"
              :data-theme-card="row.id"
              @click="themeStyle = row.id; saveTheme()"
            >
              <i :style="{ background: THEME_SWATCH[row.id] }" />
              <b>{{ row.name }}</b>
              <span>{{ row.hint }}</span>
            </button>
          </div>
          <div class="set-row">
            <label for="setTheme">明暗</label>
            <select id="setTheme" v-model="themeMode" @change="saveTheme">
              <option value="dark">深色</option>
              <option value="light">浅色</option>
              <option value="auto">跟随系统</option>
            </select>
            <span />
          </div>
          <div class="set-row">
            <label>强调色</label>
            <div id="setPalettes" class="palette-row">
              <button
                v-for="row in PALETTES"
                :key="row.key"
                type="button"
                class="palette-chip"
                :class="{ on: state.settings.palette === row.key }"
                :data-palette="row.key"
                :title="row.name"
                @click="pickPalette(row.key)"
              >
                <i :style="{ background: row.accent || 'linear-gradient(135deg,#4fd6c4,#8b7cff)' }" />
                <span>{{ row.name }}</span>
              </button>
              <span class="palette-custom" :class="{ on: state.settings.palette === 'custom' }">自定义</span>
            </div>
            <span />
          </div>
          <div class="set-row">
            <label for="setHallLayout">主页布局</label>
            <select id="setHallLayout" v-model="hallLayout" @change="saveHallLayout">
              <option value="list">大图 + 侧列表</option>
              <option value="ring">环形队列</option>
              <option value="flat">平铺横滑</option>
            </select>
            <span />
          </div>
          <div class="set-row">
            <label for="setKen">Ken Burns</label>
            <el-switch id="setKen" v-model="kenBurns" @change="saveKen" />
            <span />
          </div>
          <div class="set-row">
            <label for="setTray">关闭到托盘</label>
            <el-switch id="setTray" v-model="closeToTray" @change="saveTray" />
            <span />
          </div>
          <p class="set-note" data-slot="note">
            主题只改视觉语言，不改布局与功能。四套风格各有深 / 浅两态，
            切换立即生效，不需要重启。
          </p>
        </div>

        <!-- 资料源 -->
        <div class="set-pane" :class="{ on: state.settingsTab === 'meta' }" data-pane="meta">
          <h3 data-slot="section-title">资料源</h3>
          <button id="btnSources" class="menu-row" data-slot="row" type="button" @click="emitUi('source:open')">
            <span>管理资料源</span><span id="sourcesHint" class="menu-hint">{{ sourceHint }}</span>
          </button>
          <button id="btnSteamScan" class="menu-row" data-slot="row" type="button" @click="emitUi('steam:open')">
            <span>扫描 Steam 库</span><span class="menu-hint">按 appid 取资料</span>
          </button>
          <button id="btnRefreshAll" class="menu-row" data-slot="row" type="button" @click="startRefreshAll">
            <span>重新抓取全部</span><span id="refreshHint" class="menu-hint">{{ refreshHint }}</span>
          </button>
          <div class="set-row">
            <label for="setLang">匹配语言</label>
            <select id="setLang" v-model="lang" @change="saveSetting('lang', lang)">
              <option value="schinese">简体中文</option>
              <option value="tchinese">繁体中文</option>
              <option value="japanese">日语</option>
              <option value="english">英语</option>
            </select>
            <span />
          </div>
          <div class="set-row">
            <label for="setMerge">多源补图</label>
            <el-switch id="setMerge" v-model="mergeImages" @change="saveMerge" />
            <span />
          </div>
        </div>

        <!-- 简介翻译 -->
        <div class="set-pane" :class="{ on: state.settingsTab === 'trans' }" data-pane="trans">
          <h3 data-slot="section-title">简介翻译</h3>
          <div class="set-row">
            <label for="setTransEnabled">启用</label>
            <el-switch id="setTransEnabled" v-model="transEnabled"
                       @change="saveSetting('translate_enabled', transEnabled)" />
            <span />
          </div>
          <div class="set-row">
            <label for="setTransProvider">翻译方式</label>
            <select id="setTransProvider" v-model="transProvider" @change="saveSetting('translate_provider', transProvider)">
              <option value="auto">自动（LLM 优先，失败回落免费接口）</option>
              <option value="llm">仅 LLM</option>
              <option value="free">仅免费接口</option>
              <option v-for="plugin in translatorPlugins" :key="plugin.id" :value="`plugin:${plugin.id}`">
                插件：{{ plugin.name || plugin.id }}
              </option>
            </select>
            <span />
          </div>
          <div class="set-row">
            <label for="setTransBase">接口地址</label>
            <el-input id="setTransBase" v-model="transBase" placeholder="https://api.openai.com/v1" />
            <span />
          </div>
          <div class="set-row">
            <label for="setTransKey">API Key</label>
            <el-input id="setTransKey" v-model="transKey" type="password" show-password />
            <span />
          </div>
          <div class="set-row">
            <label for="setTransModel">模型</label>
            <el-input id="setTransModel" v-model="transModel" placeholder="gpt-4o-mini" />
            <span />
          </div>
          <div class="set-actions">
            <el-button id="transTest" class="btn glass-btn" @click="testTranslation">测试接口</el-button>
            <el-button id="btnTranslateAll" class="btn glass-btn" @click="startTranslateAll">
              翻译全部简介
            </el-button>
            <span id="translateHint" class="hint">{{ translateHint }}</span>
          </div>
          <p id="transStatus" class="set-note">—</p>
          <div class="set-row">
            <label for="setShowOriginal">显示原文</label>
            <el-switch id="setShowOriginal" v-model="showOriginal" @change="saveShowOriginal" />
            <span />
          </div>
        </div>

        <!-- 网络 -->
        <div class="set-pane" :class="{ on: state.settingsTab === 'net' }" data-pane="net">
          <h3 data-slot="section-title">网络</h3>
          <div class="set-row">
            <label for="setProxyMode">代理</label>
            <select id="setProxyMode" v-model="proxyMode" @change="saveProxy('proxy_mode', proxyMode)">
              <option value="auto">自动（系统代理）</option>
              <option value="direct">直连</option>
              <option value="manual">手动</option>
            </select>
            <span />
          </div>
          <div class="set-row">
            <label for="setProxyUrl">代理地址</label>
            <el-input id="setProxyUrl" v-model="proxyUrl" placeholder="http://127.0.0.1:7890"
                   @change="saveProxy('proxy_url', proxyUrl)" />
            <span />
          </div>
          <div class="set-row">
            <label for="setProxyFallback">失败直连</label>
            <input id="setProxyFallback" v-model="proxyFallback" class="switch" type="checkbox"
                   @change="saveProxy('proxy_fallback', proxyFallback)">
            <span />
          </div>
          <div class="set-actions">
            <el-button id="netTest" class="btn glass-btn" @click="testNetwork">开始测试</el-button>
            <span id="netHint" class="hint">会依次连五个公开端点</span>
          </div>
          <p id="netStatus" class="set-note">{{ netStatus }}</p>
          <div id="netResults" class="net-results">
            <div v-for="row in netRows" :key="row.name" class="net-line" :class="{ ok: row.ok }">
              <i class="dot" /><span class="name">{{ row.name }}</span>
              <span class="detail">{{ row.detail }}</span>
            </div>
          </div>
        </div>

        <!-- 转区启动 -->
        <div class="set-pane" :class="{ on: state.settingsTab === 'locale' }" data-pane="locale">
          <h3 data-slot="section-title">转区启动</h3>
          <div class="set-row">
            <label for="setLocaleDefault">默认开启</label>
            <input id="setLocaleDefault" v-model="localeDefault" class="switch" type="checkbox"
                   @change="saveLocaleDefault">
            <span />
          </div>
          <div class="set-row">
            <label for="setLePath">LEProc.exe</label>
            <el-input id="setLePath" v-model="lePath" readonly />
            <span />
          </div>
          <div class="set-actions">
            <el-button id="setLePick" class="mini-btn" @click="pickLocale">指定…</el-button>
            <el-button id="setLeRefresh" class="btn glass-btn" @click="refreshLocale">重新检测</el-button>
            <el-button id="setLeDownload" class="btn glass-btn" @click="openLe">打开下载页</el-button>
          </div>
          <p id="leStatus" class="set-note">{{ leStatus }}</p>
          <div id="leProfiles" class="le-profiles">
            <span v-for="row in leProfiles" :key="row.guid || row.name" class="src-badge">{{ row.name || row.guid }}</span>
          </div>
        </div>

        <!-- 游戏内翻译 -->
        <div class="set-pane" :class="{ on: state.settingsTab === 'vntext' }" data-pane="vntext">
          <h3 data-slot="section-title">游戏内翻译</h3>
          <p id="vnStatus" class="set-note">{{ vnStatus }}</p>
          <div class="set-row">
            <label for="setVnEngine">取词方式</label>
            <select id="setVnEngine" v-model="vnEngine" @change="saveVn('vntext_engine', vnEngine)">
              <option value="auto">自动（Textractor 优先）</option>
              <!-- 值必须与后端 vntext_engine 的取值表一致：auto | hook | ocr -->
              <option value="hook">仅 Textractor</option>
              <option value="ocr">仅 OCR</option>
            </select>
            <span />
          </div>
          <div class="set-row">
            <label for="setVnPath">TextractorCLI</label>
            <el-input id="setVnPath" v-model="vnPath" readonly />
            <span />
          </div>
          <div class="set-actions">
            <el-button id="setVnPick" class="mini-btn" @click="pickTractor">指定…</el-button>
            <el-button id="setVnDownload" class="btn glass-btn" @click="openTractorPage">打开下载页</el-button>
            <el-button id="setVnRefresh" class="btn glass-btn" @click="refreshVntext">重新检测</el-button>
            <el-button id="setVnLang" class="btn glass-btn" @click="openLanguageSettings">语言设置</el-button>
          </div>
          <div id="setVnBuilds" class="vn-builds">
            <button
              v-for="build in vnBuilds"
              :key="build.path"
              class="vn-build"
              :class="{ on: build.active }"
              type="button"
              @click="pickBuild(build)"
            >
              <span>{{ build.path }}</span><b>{{ build.bits }} 位</b>
            </button>
          </div>
          <p id="setVnOcr" class="set-note">{{ vnOcr }}</p>
          <div class="set-row">
            <label for="setVnContext">上下文句数</label>
            <el-slider id="setVnContext" v-model="vnContext" :min="0" :max="12" :step="1"
                       :show-tooltip="false" aria-label="上下文句数"
                       @change="saveVn('vntext_context_lines', vnContext)" />
            <span id="setVnContextVal">{{ vnContext }}</span>
          </div>
          <div class="set-row">
            <label for="setVnAuto">自动开启</label>
            <el-switch id="setVnAuto" v-model="vnAuto"
                       @change="saveVn('vntext_auto_start', vnAuto)" />
            <span />
          </div>
          <div class="set-row">
            <label for="setVnFont">悬浮窗字号</label>
            <el-slider id="setVnFont" v-model="vnFont" :min="12" :max="40" :step="1"
                       :show-tooltip="false" aria-label="悬浮窗字号"
                       @change="saveOverlay({ font: vnFont })" />
            <span id="setVnFontVal">{{ vnFont }}px</span>
          </div>
          <div class="set-row">
            <label for="setVnOpacity">悬浮窗不透明度</label>
            <el-slider id="setVnOpacity" v-model="vnOpacity" :min="35" :max="100" :step="1"
                       :show-tooltip="false" aria-label="悬浮窗不透明度"
                       @change="saveOverlay({ opacity: vnOpacity / 100 })" />
            <span id="setVnOpacityVal">{{ vnOpacity }}%</span>
          </div>
          <h3 data-slot="section-title">术语表</h3>
          <div class="set-row">
            <label for="glossarySrc">原文</label>
            <el-input id="glossarySrc" v-model="glossarySrc" />
            <span />
          </div>
          <div class="set-row">
            <label for="glossaryDst">译文</label>
            <el-input id="glossaryDst" v-model="glossaryDst" />
            <span />
          </div>
          <div class="set-actions">
            <span class="get-toggle">
              <el-switch id="glossaryGame" v-model="glossaryGame" size="small" />
              <span>仅当前游戏</span>
            </span>
            <el-button id="glossaryAdd" class="mini-btn" @click="addGlossary">加入术语表</el-button>
          </div>
          <div id="glossaryList" class="glossary-list">
            <div v-for="row in glossary" :key="row.game_id + '|' + row.source" class="glossary-row">
              <span>{{ row.source }}</span><b>{{ row.target }}</b>
              <i v-if="row.game_id" class="hint">·本作</i>
              <el-button type="button" class="mini-btn" @click="removeGlossary(row)">删除</el-button>
            </div>
          </div>
        </div>

        <!-- 插件 -->
        <div class="set-pane" :class="{ on: state.settingsTab === 'plugins' }" data-pane="plugins">
          <h3 data-slot="section-title">插件</h3>
          <p class="set-note" data-slot="note">
            把资料源 / 翻译引擎插件放进 <code>data/plugins/&lt;kind&gt;/&lt;id&gt;/</code>，
            带 <code>plugin.json</code> 清单即可被加载。插件与游戏同权限运行，只装你信任的。
          </p>
          <div class="set-actions">
            <el-button id="btnPluginRescan" class="btn glass-btn" @click="rescanPlugins">重新扫描插件</el-button>
            <el-button id="btnPluginOpenDir" class="btn glass-btn" @click="openDataDir">打开数据目录</el-button>
          </div>
          <div id="pluginList" class="plugin-list">
            <div v-for="plugin in plugins" :key="plugin.id" class="plugin-row" :class="{ ok: plugin.state === 'ok' }">
              <div class="plugin-line">
                <i class="dot" />
                <b class="plugin-name">{{ plugin.name || plugin.id }}</b>
                <span class="src-badge">{{ PLUGIN_KINDS[plugin.kind] || plugin.kind }}</span>
                <span class="plugin-state">{{ PLUGIN_STATES[plugin.state] || plugin.state }}</span>
                <span class="plugin-meta">{{ plugin.id }} · v{{ plugin.version || "—" }} · 失败 {{ plugin.failures || 0 }} 次</span>
              </div>
              <div v-if="plugin.detail" class="plugin-detail">{{ plugin.detail }}</div>
              <div class="plugin-foot">
                <span>权限：{{ (plugin.permissions || []).map((key: string) => PLUGIN_PERMS[key] || key).join(" / ") || "未声明" }}</span>
                <code class="plugin-path">{{ plugin.path }}</code>
              </div>
            </div>
            <p v-if="!plugins.length" class="hint">还没有插件。放进插件目录后点「重新扫描插件」。</p>
          </div>
          <p id="pluginDir" class="set-note">{{ pluginDir }}</p>
        </div>

        <!-- 关于 -->
        <div class="set-pane" :class="{ on: state.settingsTab === 'about' }" data-pane="about">
          <h3 data-slot="section-title">关于</h3>
          <p class="set-note" data-slot="note">版本 <b id="aboutVersion">{{ state.version || "—" }}</b></p>
          <p class="set-note" data-slot="note">数据目录 <code id="aboutDataDir">{{ dataDir || "—" }}</code></p>
          <div class="set-actions">
            <el-button id="btnOpenData" class="btn glass-btn" @click="openDataDir">打开数据目录</el-button>
            <el-button id="btnExport" class="btn glass-btn" @click="exportLibrary">导出游戏库</el-button>
            <el-button id="btnImportLib" class="btn glass-btn" @click="importLibrary">导入游戏库</el-button>
            <el-button id="btnDiagnostics" class="btn glass-btn" @click="exportDiagnostics">导出诊断包</el-button>
          </div>
          <p id="diagHint" class="set-note">出问题时把诊断包发给维护者，里面是脱敏后的日志与配置。</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import { call, recordError } from "@/core/api"
import { emitUi, onUi } from "@/core/bus"
import { closeSettings, runtime } from "@/core/app"
import { applySettings, startRefreshAll, startTranslateAll, refreshLibrary } from "@/core/actions"
import { state, toast } from "@/core/store"
import { PALETTES, THEMES, applyTheme } from "@/core/theme"
import { modal } from "@/core/modal"
import { domValue } from "@/core/dom"

const props = defineProps<{ hidden: boolean }>()

const TABS = [
  { id: "look", label: "外观" },
  { id: "meta", label: "资料源" },
  { id: "trans", label: "简介翻译" },
  { id: "net", label: "网络" },
  { id: "locale", label: "转区启动" },
  { id: "vntext", label: "游戏内翻译" },
  { id: "plugins", label: "插件" },
  { id: "about", label: "关于" },
]
const LE_URL = "https://github.com/xupefei/Locale-Emulator/releases"
const TRACTOR_URL = "https://github.com/Artikash/Textractor/releases"
const THEME_SWATCH: Record<string, string> = {
  aurora: "linear-gradient(135deg, #4fd6c4, #8b7cff)",
  gallery: "linear-gradient(135deg, #ffffff, #3f63e8)",
  screening: "linear-gradient(135deg, #e9a13b, #15110c)",
  shelf: "linear-gradient(135deg, #c8a24a, #1b1815)",
}
const PLUGIN_STATES: Record<string, string> = {
  ok: "正常", "manifest-error": "清单错误", incompatible: "版本不兼容",
  "load-error": "加载失败", "init-error": "初始化失败", duplicate: "重复 ID",
  disabled: "已自动禁用",
}
const PLUGIN_KINDS: Record<string, string> = { sources: "资料源", translators: "翻译引擎" }
const PLUGIN_PERMS: Record<string, string> = {
  network: "联网", "files:read": "读文件", "files:write": "写文件", process: "启动进程",
}

const themeStyle = ref("aurora")
const themeMode = ref("dark")
const hallLayout = ref("list")
const kenBurns = ref(false)
const closeToTray = ref(false)
const lang = ref("schinese")
const mergeImages = ref(true)
const transEnabled = ref(true)
const transProvider = ref("auto")
const transBase = ref("")
const transKey = ref("")
const transModel = ref("")
const showOriginal = ref(false)
const proxyMode = ref("auto")
const proxyUrl = ref("")
const proxyFallback = ref(true)
const netStatus = ref("—")
const netRows = ref<{ name: string; ok: boolean; detail: string }[]>([])
const localeDefault = ref(false)
const lePath = ref("")
const leStatus = ref("正在检测 Locale Emulator…")
const leProfiles = ref<any[]>([])
const vnStatus = ref("—")
const vnEngine = ref("auto")
const vnPath = ref("")
const vnBuilds = ref<any[]>([])
const vnOcr = ref("—")
const vnContext = ref(4)
const vnAuto = ref(false)
const vnFont = ref(20)
const vnOpacity = ref(90)
const glossarySrc = ref("")
const glossaryDst = ref("")
const glossaryGame = ref(false)
const glossary = ref<any[]>([])
const plugins = ref<any[]>([])
const pluginDir = ref("")
const dataDir = ref("")
const refreshHint = ref("")
const translateHint = ref("")

const themeHint = computed(() => THEMES.find((row) => row.id === themeStyle.value)?.hint || "")
const translatorPlugins = computed(() => plugins.value.filter((row) => row.kind === "translators"))
const sourceHint = computed(() => `${(state.sources || []).length} 个可用`)

function syncFromSettings(): void {
  const s = state.settings
  themeStyle.value = String(s.theme || "aurora")
  themeMode.value = String(s.theme_mode || "dark")
  hallLayout.value = ["list", "ring", "flat"].includes(String(s.hall_layout))
    ? String(s.hall_layout) : "list"
  kenBurns.value = !!s.ken_burns
  closeToTray.value = !!s.close_to_tray
  lang.value = String(s.lang || "schinese")
  mergeImages.value = s.sources ? s.sources.merge_images !== false : true
  transEnabled.value = s.translate_enabled !== false
  transProvider.value = String(s.translate_provider || "auto")
  transBase.value = String(s.translate_base_url || "")
  transKey.value = String(s.translate_api_key || "")
  transModel.value = String(s.translate_model || "")
  showOriginal.value = !!s.show_original
  vnEngine.value = String(s.vntext_engine || "auto")
  // 键名与后端一致：vntext_context_lines / vntext_auto_start（config.py 的 DEFAULTS）
  vnContext.value = Number(s.vntext_context_lines ?? 4)
  vnAuto.value = !!s.vntext_auto_start
  vnFont.value = Number(s.vntext_overlay?.font ?? 20)
  vnOpacity.value = Math.round(Number(s.vntext_overlay?.opacity ?? 0.9) * 100)
  applyTheme(state.settings)
}

async function saveSetting(key: string, value: unknown): Promise<void> {
  state.settings[key] = value
  applySettings({ [key]: value })
  await call("set_setting", key, value)
}
async function saveTheme(): Promise<void> {
  await call("set_setting", "theme", themeStyle.value)
  await call("set_setting", "theme_mode", themeMode.value)
  state.settings.theme = themeStyle.value
  state.settings.theme_mode = themeMode.value
  applyTheme(state.settings)
  toast(`已切换到「${THEMES.find((row) => row.id === themeStyle.value)?.name}」`)
}
async function saveHallLayout(): Promise<void> {
  await saveSetting("hall_layout", hallLayout.value)
  runtime.ring?.applyLayout()
  toast(hallLayout.value === "list" ? "主页布局：大图 + 侧列表"
    : hallLayout.value === "flat" ? "主页布局：平铺横滑" : "主页布局：环形队列")
}
async function pickPalette(key: string): Promise<void> {
  const preset = PALETTES.find((row) => row.key === key)
  if (!preset) return
  state.settings.palette = preset.key
  document.documentElement.dataset.palette = preset.key
  if (preset.accent) {
    document.documentElement.style.setProperty("--a-main", preset.accent)
    document.documentElement.style.setProperty("--a-2", preset.accent2)
    document.documentElement.style.setProperty("--accent", preset.accent)
    document.documentElement.style.setProperty("--accent-2", preset.accent2)
    state.settings.accent = preset.accent
  } else {
    document.documentElement.style.removeProperty("--a-main")
    document.documentElement.style.removeProperty("--a-2")
    document.documentElement.style.removeProperty("--accent")
    document.documentElement.style.removeProperty("--accent-2")
  }
  await call("set_setting", "palette", preset.key)
  toast(`已应用配色：${preset.name}`)
}
async function saveKen(): Promise<void> {
  await saveSetting("ken_burns", kenBurns.value)
  runtime.background?.applyKenBurns?.(kenBurns.value)
}
async function saveTray(): Promise<void> {
  await saveSetting("close_to_tray", closeToTray.value)
  toast(closeToTray.value ? "关窗口时缩到托盘，游戏继续跑" : "关窗口即退出")
}
async function saveMerge(): Promise<void> {
  const res = await call("set_merge_sources", mergeImages.value)
  if (state.settings.sources) state.settings.sources.merge_images = res?.merge_images
  toast(mergeImages.value ? "已开启多源补图" : "已关闭多源补图")
}
async function saveShowOriginal(): Promise<void> {
  await saveSetting("show_original", showOriginal.value)
  emitUi("render")
}
async function saveProxy(key: string, value: unknown): Promise<void> {
  // 探针 / 自动填充可能直接写 DOM 值，代理地址这类输入以 DOM 为准
  const payload = key === "proxy_url" ? domValue("setProxyUrl", String(value || "")) : value
  const res = await call("set_proxy_option", key, payload)
  if (res && res.ok === false) toast("代理设置无效：" + (res.error || ""))
  await refreshNetwork()
}
async function saveLocaleDefault(): Promise<void> {
  await call("set_locale_option", "locale_default", localeDefault.value)
  toast(localeDefault.value ? "新导入的游戏默认开启转区" : "已关闭默认转区")
}
async function saveVn(key: string, value: unknown): Promise<void> {
  // 后端只认自己那张取值表（见 app/services/vntext.py），写错键名会回 ok:false，
  // 静默吞掉就变成「界面能拖、设置没存」——所以这里必须把失败喊出来。
  const res = await call("set_vntext_option", key, value)
  if (res && res.ok === false) {
    toast(`设置没生效（${key}）：${res.error || "未知原因"}`)
    recordError("游戏内翻译设置", new Error(`${key}: ${res.error || ""}`))
  }
  await refreshVntext()
}
async function saveOverlay(patch: Record<string, unknown>): Promise<void> {
  const res = await call("set_overlay_style", patch)
  if (res && res.ok === false) {
    toast("悬浮窗外观没保存：" + (res.error || "未知原因"))
    recordError("悬浮窗外观", new Error(JSON.stringify(patch)))
  }
}

async function refreshNetwork(): Promise<void> {
  try {
    const net = await call("get_network_status")
    if (!net || !net.ok) return
    proxyMode.value = net.mode || "auto"
    proxyUrl.value = net.url || ""
    proxyFallback.value = net.fallback !== false
    netStatus.value = net.proxy
      ? `当前生效：${net.proxy}（来源：${net.source}）`
      : `当前生效：直连（来源：${net.source || "系统设置"}）`
  } catch (error) {
    netStatus.value = "读取代理设置失败：" + (error as Error).message
  }
}
async function testNetwork(): Promise<void> {
  netRows.value = [{ name: "正在测试…", ok: false, detail: "" }]
  try {
    const res = await call("test_network")
    netRows.value = res?.results || []
    if (res?.proxy) netStatus.value = `当前生效：${res.proxy}（来源：${res.source}）`
  } catch (error) {
    netRows.value = [{ name: "测试失败", ok: false, detail: (error as Error).message }]
  }
}
async function refreshLocale(): Promise<void> {
  try {
    const st = await call("get_locale_status")
    state.locale = st || {}
    lePath.value = st?.proc || ""
    localeDefault.value = !!st?.default_enabled
    leStatus.value = st?.available
      ? `已检测到 Locale Emulator：${st.proc}`
      : (st?.proc ? "指定的 LEProc.exe 不可用（缺少运行时文件），请重新选择。"
        : "未检测到 Locale Emulator。装好后点「重新检测」，或手动指定 LEProc.exe。")
    leProfiles.value = st?.profiles || []
  } catch (error) {
    leStatus.value = "检测失败：" + (error as Error).message
  }
}
async function pickLocale(): Promise<void> {
  const res = await call("pick_locale_proc")
  if (!res || res.cancelled) return
  if (!res.ok) { toast("这个路径不可用：" + (res.error || "")); return }
  await refreshLocale()
  toast("已设置 Locale Emulator 路径")
}
function openLe(): void { void call("open_url", LE_URL) }
function openTractorPage(): void { void call("open_url", TRACTOR_URL) }
function openLanguageSettings(): void { void call("open_language_settings") }
function openDataDir(): void { void call("open_data_dir") }

async function refreshVntext(): Promise<void> {
  try {
    const st = await call("get_vntext_status")
    state.vntext = st || {}
    // 判据（tools/e2e.py）：这一行里必须出现 TextractorCLI，运行中还要出现「正在翻译」
    const tractor = st?.tractor || {}
    const head = st?.running ? "正在翻译" : "未在翻译"
    vnStatus.value = tractor.found
      ? `${head} · TextractorCLI：${tractor.path}`
      : `${head} · 没找到 TextractorCLI，请在下面指定，或改用 OCR 模式`
    vnPath.value = tractor.path || tractor.saved || ""
    vnBuilds.value = st?.builds || []
    vnOcr.value = st?.ocr?.ok
      ? `OCR 可用（语言：${(st.ocr.langs || []).join(" / ") || "—"}）`
      : `OCR 不可用：${st?.ocr?.error || "未安装语言包"}`
    vnContext.value = Number(st?.context_lines ?? vnContext.value)
    vnAuto.value = !!st?.auto_start
    vnEngine.value = String(st?.mode || vnEngine.value)
  } catch (error) {
    vnStatus.value = "读取状态失败：" + (error as Error).message
  }
}
async function pickTractor(): Promise<void> {
  const res = await call("pick_textractor")
  if (!res || res.cancelled) return
  await refreshVntext()
  toast(res.ok ? "已设置 TextractorCLI 路径" : "这个路径不可用")
}
async function pickBuild(build: any): Promise<void> {
  await call("set_vntext_option", "vntext_tractor_path", build.path)
  await refreshVntext()
  toast(`已选用 ${build.bits} 位 TextractorCLI`)
}

async function refreshGlossary(): Promise<void> {
  try {
    const payload = await call("list_glossary")
    // 后端的形状是 { global: {原文: 译文}, games: {game_id: {原文: 译文}} }
    const gameId = String(state.focus || "")
    const rows: { source: string; target: string; game_id: string }[] = []
    for (const [source, target] of Object.entries(payload?.global || {})) {
      rows.push({ source, target: String(target), game_id: "" })
    }
    for (const [source, target] of Object.entries(payload?.games?.[gameId] || {})) {
      rows.push({ source, target: String(target), game_id: gameId })
    }
    glossary.value = rows
  } catch { /* 离线忽略 */ }
}
async function addGlossary(): Promise<void> {
  if (!glossarySrc.value.trim() || !glossaryDst.value.trim()) { toast("原文和译文都要填"); return }
  const res = await call("set_glossary_entry", glossarySrc.value.trim(),
    glossaryDst.value.trim(), glossaryGame.value ? String(state.focus || "") : "")
  if (res && res.ok === false) { toast("术语表更新失败：" + (res.error || "")); return }
  glossarySrc.value = ""
  glossaryDst.value = ""
  await refreshGlossary()
  toast("已加入术语表")
}
async function removeGlossary(row: any): Promise<void> {
  await call("remove_glossary_entry", row.source, row.game_id || "")
  await refreshGlossary()
  toast("已删除术语")
}

async function refreshPlugins(rescan = false): Promise<void> {
  try {
    const payload = rescan ? await call("rescan_plugins") : await call("list_plugins")
    plugins.value = payload?.plugins || []
    pluginDir.value = payload?.dir ? `插件目录：${payload.dir}` : ""
  } catch (error) {
    toast("读取插件失败：" + (error as Error).message)
  }
}
async function rescanPlugins(): Promise<void> {
  await refreshPlugins(true)
  toast(`已重新扫描插件：${plugins.value.length} 个`)
}

async function testTranslation(): Promise<void> {
  const provider = domValue("setTransProvider", transProvider.value)
  const res = await call("test_translation", {
    translate_provider: provider,
    translate_base_url: domValue("setTransBase", transBase.value.trim()),
    translate_api_key: domValue("setTransKey", transKey.value.trim()),
    translate_model: domValue("setTransModel", transModel.value.trim()),
  })
  if (res?.ok) {
    toast("翻译接口可用")
    document.getElementById("transStatus")!.textContent = `可用（${res.provider}）：${res.text}`
  } else {
    toast("翻译接口不可用")
    document.getElementById("transStatus")!.textContent = "不可用：" + ((res && res.error) || "未知错误")
  }
}

async function exportLibrary(): Promise<void> {
  const res = await call("export_library")
  if (!res || res.cancelled) return
  if (!res.ok) { toast("导出失败：" + (res.error || "")); return }
  toast(`已导出 ${res.games} 个游戏到 ${String(res.path).split("\\").pop()}`, 4200)
}
async function importLibrary(): Promise<void> {
  const res = await call("import_library")
  if (!res || res.cancelled) return
  if (!res.ok) {
    toast(res.error === "bad-file" ? "这个文件不是 Aurora 导出的游戏库" : "导入失败")
    return
  }
  await refreshLibrary()
  toast(`导入完成：新增 ${res.added} 个，跳过 ${res.skipped} 个`)
}
async function exportDiagnostics(): Promise<void> {
  const res = await call("export_diagnostics")
  if (!res || !res.ok) {
    toast("导出诊断包失败：" + ((res && res.error) || "未知错误"))
    return
  }
  const node = document.getElementById("diagHint")
  if (node) node.textContent = `已导出（${(res.bytes / 1024).toFixed(1)} KB）：${res.path}`
  toast("诊断包已导出，出问题时把这个 zip 发给维护者")
}

async function refreshAll(): Promise<void> {
  document.getElementById("aboutVersion")!.textContent = state.version || "—"
  try {
    const info = await call("bootstrap")
    dataDir.value = info.data_dir || "—"
    applySettings(info.settings || {})
    syncFromSettings()
  } catch { /* 离线也要能开设置 */ }
  await refreshPlugins()
  await refreshNetwork()
  await refreshLocale()
  await refreshVntext()
  await refreshGlossary()
}

onMounted(() => {
  onUi("settings:applied", syncFromSettings)
  onUi("settings:open", () => { void refreshAll() })
  onUi("batch", (payload: any) => {
    if (payload.kind === "translate") translateHint.value = `${payload.done}/${payload.total}`
    else refreshHint.value = `${payload.done}/${payload.total}`
  })
  // 只在「正看着这一页」时才跟着刷新：
  // 台词密的时候是 19 句/秒，每条都打一次桥接往返会把 GUI 线程堵死
  // （v1 core/events.js 就是带条件的，这里必须保持一致）。
  onUi("vntext:line", () => {
    if (state.settingsOpen && state.settingsTab === "vntext") void refreshGlossary()
  })
  onUi("hooksearch:status", () => {
    if (state.settingsOpen && state.settingsTab === "vntext") void refreshVntext()
  })
  syncFromSettings()
})
defineExpose({ refreshAll, syncFromSettings })
</script>
