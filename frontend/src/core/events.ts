/**
 * Aurora v2 · 推送事件分发（14 个主题，信封 {topic, seq, ts, payload}）
 *
 * 每个主题的语义与 v1 core/events.js 一致；v2 里「界面要动的部分」通过 core/bus
 * 发内部信号（vntext:refresh / candidates:open …），避免事件模块反向依赖组件。
 */
import { emitUi } from "@/core/bus"
import { state, patchGame, pushGame, setBusy, toast, upsertGame } from "@/core/store"
import { currentGame } from "@/core/store"

/** 搜索结束却没有封面：说明图片是界面侧加载（走系统代理），同一个游戏只提醒一次。 */
const coverHinted = new Set<string>()
const lastSeq = new Map<string, number>()

function hintCoverOnce(game: any): void {
  if (!game?.id || coverHinted.has(game.id)) return
  if (game.cover || game.custom_cover || (game.cover_sources || []).length) return
  coverHinted.add(game.id)
  toast("没抓到封面：图片由界面直接加载（走系统代理），可在「设置 → 网络」测试连通性", 5400)
}

function notifyLocaleStart(mode?: string): void {
  if (mode === "no-le") toast("没检测到 Locale Emulator，已按普通方式启动", 4600)
  else if (mode === "unsupported-target") {
    toast("目标不是 32 位 exe，Locale Emulator 带不动，已按普通方式启动", 4600)
  } else if (mode === "locale") toast("已用指定的 LE 配置转区启动")
  else if (mode === "locale-default") toast("已用 LE 默认配置转区启动")
}

function onGameState(event: string, payload: any): void {
  const running = event === "game:running" ? true : event === "game:stopped" ? false : payload.running
  const isNew = upsertGame(payload, { running })
  setBusy(payload.id, false)
  emitUi("render")
  if (event === "game:running") notifyLocaleStart(payload.locale)
  if (event === "game:updated" && payload.metadata_state === "ok") hintCoverOnce(payload)
  if (isNew && !currentGame()) emitUi("focus", payload.id)
  else if (payload.id === state.focus) emitUi("background")
}

const handlers: Record<string, (payload: any) => void> = {
  "game:updated": (payload) => onGameState("game:updated", payload),
  "game:stopped": (payload) => onGameState("game:stopped", payload),
  "game:running": (payload) => onGameState("game:running", payload),

  "metadata:searching": (payload) => {
    setBusy(payload.id, true)
    emitUi("render")
  },

  "games:imported": (payload) => {
    for (const game of payload.games || []) upsertGame(game)
    const ids: string[] = payload.ids || []
    emitUi("render")
    if (ids.length) emitUi("focus", ids[ids.length - 1])
    const ignored = payload.ignored || 0
    toast(ids.length
      ? `已导入 ${ids.length} 个游戏`
      : "没有可导入的 exe" + (ignored ? "（已忽略非 exe 文件）" : ""),
      ids.length ? 2600 : 4000)
  },

  "metadata:notfound": (payload) => {
    setBusy(payload.id, false)
    let game = state.games.find((row) => row.id === payload.id)
    if (!game && payload.game) {
      pushGame(payload.game)
      if (!currentGame()) state.focus = payload.id
      game = payload.game
    }
    if (game) {
      patchGame(payload.id, { metadata_state: "notfound", metadata_note: payload.note })
    }
    emitUi("render")
    const watching = state.focus === payload.id && state.page === "game" && !payload.quiet
      && !state.settingsOpen
    if (watching) {
      emitUi("candidates", { rows: payload.candidates, query: "", note: payload.note || "没有找到匹配结果" })
      toast(payload.note || "没有找到匹配结果")
    } else if (game && !payload.quiet) {
      toast(`${game.name}：${payload.note || "没有找到匹配结果"}`, 3600)
    }
  },

  "batch:progress": (payload) => {
    const batch = state.batch
    if (!batch) return
    batch.done = payload.done
    batch.total = payload.total
    emitUi("batch", { kind: batch.kind, done: payload.done, total: payload.total })
  },

  "batch:done": (payload) => {
    const batch = state.batch
    state.batch = null
    emitUi("batch", { kind: batch?.kind || "refresh", done: payload.done, total: payload.total })
    if (batch?.kind === "steam") {
      emitUi("steam:done")
      toast(`Steam 导入完成：${payload.imported || 0} 个游戏`)
    } else if (batch?.kind === "translate") {
      toast(`简介翻译完成：翻译 ${payload.translated || 0} 个，跳过 ${payload.skipped || 0} 个`
        + (payload.failed ? `，失败 ${payload.failed} 个` : ""), 4200)
    } else {
      toast(`已重新抓取 ${payload.total} 个游戏的信息`)
    }
    emitUi("library:refresh")
  },

  "metadata:error": (payload) => {
    setBusy(payload.id, false)
    emitUi("render")
    toast("搜索出错：" + payload.note)
  },

  "translate:done": (payload) => {
    if (!payload.manual) return
    const provider = String(payload.provider || "")
    if (payload.changed) {
      if (provider.startsWith("plugin:")) toast(`已用插件 ${provider.slice(7)} 翻译简介`)
      else toast(provider === "llm" ? "已用 LLM 翻译简介" : "已用免费接口翻译简介")
    } else if (payload.error === "empty") toast("这款游戏还没有简介可翻译")
    else if (payload.error === "stale") toast("简介刚被更新，请再翻译一次")
    else if (payload.error === "busy") toast("正在翻译中…")
    else if (payload.error === "plugin-unavailable") {
      toast("翻译插件不可用（没加载或已被禁用），详情见「设置 → 插件」")
    } else if (payload.error === "plugin-failed") {
      toast("翻译插件调用失败，简介保持原文；详情见「设置 → 插件」")
    } else if (payload.error) toast("翻译失败：" + payload.error)
    else toast("简介已经是中文，无需翻译")
    emitUi("render")
  },

  "vntext:status": (payload) => {
    state.vntext = payload || {}
    emitUi("vntext:status", payload)
  },

  "hooksearch:status": (payload) => emitUi("hooksearch:status", payload),

  "vntext:line": (payload) => emitUi("vntext:line", payload),

  "downloads:status": (payload) => {
    if (payload.kind === "warn") toast(payload.text || "下载目录里有个文件处理不了", 5200)
    else if (payload.kind === "extracted") toast(`已自动解压 ${payload.name}`, 2600)
    else if (payload.kind === "imported") {
      const count = payload.count || 0
      toast(count ? `下载目录里发现 ${count} 个游戏，已自动导入` : "下载目录有更新", 3800)
      emitUi("library:refresh")
    }
    emitUi("downloads:status", payload)
  },
}

/** 后端推来的事件入口：未知主题忽略，单个主题出错不影响别的。 */
export function emitEvent(topic: string, payload: Record<string, any> = {}): void {
  const seq = Number((payload as any)?.__seq)
  if (!Number.isNaN(seq) && seq) {
    const seen = lastSeq.get(topic) || 0
    if (seq < seen) return
    lastSeq.set(topic, seq)
  }
  const handler = handlers[topic]
  if (!handler) return
  try {
    handler(payload || {})
  } catch (error) {
    console.error(`event ${topic}`, error)
    const list = ((window as any).__auroraErrors = (window as any).__auroraErrors || [])
    list.push(`事件 ${topic}: ${(error as Error).message}`)
  }
}

/** 契约里的目标形态：整封 JSON 字符串进、分发。 */
export function dispatchEnvelope(raw: string): void {
  try {
    const envelope = JSON.parse(raw)
    emitEvent(envelope.topic, { ...(envelope.payload || {}), __seq: envelope.seq })
  } catch (error) {
    console.error("bad envelope", error)
  }
}
