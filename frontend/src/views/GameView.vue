<template>
  <section id="view" :hidden="hidden">
    <div id="bgDragArea" class="stage-top" data-drag data-slot="stage-top">
      <span id="pillSource" class="pill glass-s" :hidden="!sourceText">{{ sourceText }}</span>
      <span id="pillRunning" class="pill glass-s live" :hidden="!game?.running"><i />运行中</span>
    </div>
    <button id="btnBack" class="btn glass-btn back-pill" data-slot="back" type="button" @click="closeGame">
      <svg viewBox="0 0 24 24" class="ic"><path d="m14 6-6 6 6 6" /></svg>
      返回
    </button>
    <div class="game-body" data-slot="hero">
      <div class="game-head" data-slot="hero-label">
        <img id="gLogo" class="g-logo" :src="game?.logo || ''" alt="" :hidden="!game?.logo">
        <h1 id="gTitle" data-slot="title">{{ game?.name || "—" }}</h1>
        <div id="gChips" class="chips" data-slot="meta">
          <span v-for="chip in chips" :key="chip.text" class="chip" :class="{ accent: chip.accent }">
            {{ chip.text }}
          </span>
        </div>
        <p id="gDesc" class="desc" data-slot="desc">{{ desc }}</p>
        <button
          id="btnShowOriginal"
          class="mini-btn"
          type="button"
          :hidden="!hasBoth"
          @click="toggleOriginal"
        >{{ state.settings.show_original ? "显示译文" : "显示原文" }}</button>
        <div class="game-actions" data-slot="actions">
          <button id="btnPlay" class="btn play" type="button" data-slot="play"
                  :class="{ running: game?.running }"
                  @click="togglePlay">
            <svg viewBox="0 0 24 24" class="ic"><path d="M8 5.5v13l11-6.5z" /></svg>
            <span id="playLabel">{{ game?.running ? "结束游戏" : "开始游戏" }}</span>
          </button>
          <button id="btnBackgrounds" class="btn glass-btn" type="button" @click="emitUi('bg:open')">
            <svg viewBox="0 0 24 24" class="ic"><rect x="3.5" y="5" width="17" height="14" rx="2.5" /><path d="m6 16 4-4 3 3 2.5-2.5L18 16" /></svg>
            背景图
          </button>
          <button id="btnDetails" class="btn glass-btn" type="button" @click="emitUi('detail:open')">
            <svg viewBox="0 0 24 24" class="ic"><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5M12 8h.01" /></svg>
            详情
          </button>
          <button id="btnVntext" class="btn glass-btn" type="button" title="游戏内翻译（日文台词实时译成中文）"
                  @click="emitUi('vntext:open')">
            <svg viewBox="0 0 24 24" class="ic"><path d="M4 6h9M8.5 6v2.5c0 3.5-2 6.5-4.5 8M6 12c1.2 2.4 3 4.2 5.5 5.2" /><path d="m13 19 3.5-9 3.5 9M14.4 16h4.2" /></svg>
            翻译
          </button>
          <button id="btnMore" class="icon-btn glass-btn sq" type="button" title="更多" @click.stop="state.menus.more = !state.menus.more">
            <svg viewBox="0 0 24 24" class="ic"><circle cx="6" cy="12" r="1.4" /><circle cx="12" cy="12" r="1.4" /><circle cx="18" cy="12" r="1.4" /></svg>
          </button>
        </div>
      </div>
    </div>

    <div id="fetching" class="fetching glass" :hidden="!busy">
      <b id="fetchTitle">正在搜索游戏信息…</b>
      <span id="fetchSub">{{ (game?.queries || []).slice(0, 2).join(" / ") || game?.exe_name || "" }}</span>
    </div>

    <div id="moreMenu" class="menu glass" data-nodrag :hidden="!state.menus.more">
      <button id="menuFavorite" type="button" data-act="favorite" @click="moreAction('favorite')">
        {{ game?.favorite ? "取消收藏" : "加入收藏" }}
      </button>
      <button id="menuNameReset" type="button" data-act="name-reset" :hidden="!game?.name_custom" @click="moreAction('name-reset')">
        恢复自动命名
      </button>
      <button id="menuIconReset" type="button" data-act="icon-reset" :hidden="!game?.custom_icon" @click="moreAction('icon-reset')">
        恢复默认图标
      </button>
      <div class="menu-sep" />
      <button type="button" data-act="rename" @click="moreAction('rename')">重命名…</button>
      <button type="button" data-act="cover" @click="moreAction('cover')">更换封面…</button>
      <button type="button" data-act="icon" @click="moreAction('icon')">更换图标…</button>
      <button type="button" data-act="match" @click="moreAction('match')">手动匹配…</button>
      <button type="button" data-act="research" @click="moreAction('research')">重新搜索游戏信息</button>
      <button type="button" data-act="translate" @click="moreAction('translate')">翻译简介</button>
      <button id="menuLocale" type="button" data-act="locale" @click="moreAction('locale')">转区启动…</button>
      <div class="menu-sep" />
      <button type="button" data-act="args" @click="moreAction('args')">启动参数…</button>
      <button type="button" data-act="reveal" @click="moreAction('reveal')">打开所在目录</button>
      <button type="button" data-act="remove" class="danger" @click="moreAction('remove')">移除游戏</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue"

import { call } from "@/core/api"
import { emitUi } from "@/core/bus"
import { closeGame } from "@/core/app"
import { modal } from "@/core/modal"
import { state, toast } from "@/core/store"
import { currentGame } from "@/core/store"
import { togglePlay } from "@/core/actions"
import { clock, hours, sessionSeconds } from "@/core/time"

const props = defineProps<{ hidden: boolean }>()

const game = computed(() => currentGame())
const desc = computed(() => {
  const row = game.value
  if (!row) return ""
  const original = String(row.description_original || "").trim()
  if (state.settings.show_original && original) return original
  return row.description || row.description_translated || String(row.about || "").slice(0, 220) || ""
})
const hasBoth = computed(() => {
  const row = game.value
  return !!(row?.description_translated && String(row.description_original || "").trim()
    && row.description_translated !== row.description_original)
})
const chips = computed(() => {
  const row = game.value
  if (!row) return []
  const out: { text: string; accent?: boolean }[] = []
  if ((row.developers || [])[0]) out.push({ text: String((row.developers || [])[0]) })
  const year = String(row.release_date || "").match(/\d{4}/)?.[0]
  if (year) out.push({ text: year })
  ;(row.genres || []).slice(0, 2).forEach((genre) => out.push({ text: String(genre) }))
  if (row.metacritic) out.push({ text: `Metacritic ${row.metacritic}`, accent: true })
  if (row.locale_enabled) out.push({ text: "转区启动" })
  if ((row.play_time || 0) > 0) out.push({ text: `已玩 ${hours(row.play_time || 0)}` })
  if (row.running) out.push({ text: `运行中 · ${clock(sessionSeconds(row))}`, accent: true })
  if (row.missing) out.push({ text: "可执行文件不存在", accent: true })
  else if (row.metadata_state === "notfound" && /网络/.test(String(row.metadata_note || ""))) {
    out.push({ text: "上次搜索没连上网络", accent: true })
  }
  return out
})
const busy = computed(() => {
  const row = game.value
  return !!row && (row.metadata_state === "searching" || !!state.busy[row.id])
})
const sourceText = computed(() => {
  const row = game.value
  if (!row || (!row.data_source && !row.match_source)) return ""
  const parts: string[] = []
  if (row.data_source) {
    const meta = (state.sources || []).find((item) => item.id === row.data_source)
    parts.push(meta ? meta.name : String(row.data_source))
  }
  parts.push(row.match_source === "manual" ? "手动匹配" : "自动匹配")
  if (row.match_score != null) parts.push(`${Math.round(Number(row.match_score) * 100)}%`)
  return parts.join(" · ")
})

async function toggleOriginal(): Promise<void> {
  state.settings.show_original = !state.settings.show_original
  await call("set_setting", "show_original", state.settings.show_original)
  emitUi("render")
}

async function moreAction(action: string): Promise<void> {
  state.menus.more = false
  const row = game.value
  if (!row) return
  if (action === "favorite") {
    const res = await call("toggle_favorite", row.id)
    if (res?.game) Object.assign(row, res.game)
    emitUi("render")
    return
  }
  if (action === "name-reset") {
    const res = await call("reset_name", row.id)
    if (res?.game) Object.assign(row, res.game)
    emitUi("render")
    toast("已恢复自动命名")
    return
  }
  if (action === "icon-reset") {
    const res = await call("clear_custom_icon", row.id)
    if (res?.game) Object.assign(row, res.game)
    emitUi("render")
    toast("已恢复默认图标")
    return
  }
  if (action === "rename") {
    const value = await modal({
      title: "重命名游戏", body: "只改 Aurora 里显示的名字，不动磁盘上的文件。",
      input: true, value: row.name, okText: "保存",
    })
    if (value === null || !value) return
    const res = await call("rename_game", row.id, value)
    if (res?.game) Object.assign(row, res.game)
    emitUi("render")
    toast("已重命名")
    return
  }
  if (action === "cover") { emitUi("cover:open"); return }
  if (action === "icon") {
    const res = await call("pick_custom_icon", row.id)
    if (!res || res.cancelled) return
    if (!res.ok) { toast("选择失败：" + (res.error || "")); return }
    if (res.game) Object.assign(row, res.game)
    emitUi("render")
    toast("已应用自定义图标")
    return
  }
  if (action === "match") { emitUi("match:open"); return }
  if (action === "research") {
    toast("正在重新搜索…")
    const res = await call("search", row.id, null, true, false)
    if (res?.applied) {
      if (res.game) Object.assign(row, res.game)
      emitUi("render")
      toast("已匹配：" + row.name)
    } else {
      emitUi("candidates", { rows: res?.candidates, query: (res?.queries || [])[0] || "", note: "匹配置信度不足，请手动选择" })
      toast("匹配置信度不足，请手动选择")
    }
    return
  }
  if (action === "translate") {
    const res = await call("translate_game", row.id)
    if (!res || !res.ok) toast("翻译失败：" + ((res && res.error) || "未知错误"))
    else toast("已提交翻译")
    return
  }
  if (action === "locale") { emitUi("locale:open"); return }
  if (action === "args") {
    const value = await modal({
      title: "启动参数", body: "会追加在可执行文件之后，点下面的常用参数可快速加入。",
      input: true, value: row.launch_args || "", okText: "保存",
      presets: ["-windowed", "-fullscreen", "-dx11", "-dx12", "-novid", "-high"],
    })
    if (value === null) return
    row.launch_args = value
    await call("set_launch_args", row.id, value)
    toast("已保存启动参数")
    return
  }
  if (action === "reveal") { await call("reveal", row.id); return }
  if (action === "remove") {
    const ok = await modal({
      title: "移除游戏",
      body: `确定把「${row.name}」从库中移除吗？不会删除磁盘上的文件。`,
      okText: "移除",
    })
    if (!ok) return
    await call("remove_game", row.id)
    emitUi("library:refresh")
    toast("已移除")
  }
}

defineExpose({ togglePlay })
</script>
