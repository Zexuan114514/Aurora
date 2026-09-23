<template>
  <BackgroundLayer />
  <ToolbarBar />

  <main id="stage">
    <section id="empty" class="empty glass" :hidden="!showEmpty">
      <h2>游戏库还是空的</h2>
      <p>导入任意 <b>.exe</b> / <b>.bat</b>，Aurora 会自动匹配简介、封面与壁纸；<br>也可以直接把游戏文件夹拖进窗口。</p>
      <button id="btnImport2" class="btn primary lg" type="button" @click="importGames">导入游戏</button>
    </section>

    <HallView :hidden="hallHidden" />
    <GameView :hidden="gameHidden" />
    <CategoriesView :hidden="!showCategories" />
    <SettingsView :hidden="!state.settingsOpen" />
  </main>

  <MediaPanels />
  <SourcePanels />
  <VntextPanel />
  <AppModal />

  <div id="toast" data-slot="toast" :class="{ show: !!state.toast.text }">{{ state.toast.text }}</div>
  <div id="dropHint" class="drop-hint" :hidden="!dropHint">松手即可导入游戏</div>
  <ResizeHandles />

  <div id="boot" class="boot" :class="{ done: booted }">
    <div class="boot-logo">Aurora</div>
    <div class="boot-sub">游戏启动器</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"

import AppModal from "@/components/AppModal.vue"
import BackgroundLayer from "@/components/BackgroundLayer.vue"
import ResizeHandles from "@/components/ResizeHandles.vue"
import ToolbarBar from "@/components/ToolbarBar.vue"
import CategoriesView from "@/views/CategoriesView.vue"
import GameView from "@/views/GameView.vue"
import HallView from "@/views/HallView.vue"
import MediaPanels from "@/panels/MediaPanels.vue"
import SettingsView from "@/views/SettingsView.vue"
import SourcePanels from "@/panels/SourcePanels.vue"
import VntextPanel from "@/panels/VntextPanel.vue"
import { importGames } from "@/core/actions"
import { onUi } from "@/core/bus"
import { state } from "@/core/store"

const booted = ref(false)
const dropHint = ref(false)

const hasGames = computed(() => state.games.length > 0)
const showCategories = computed(() => !state.settingsOpen && state.view === "categories")
const showSettings = computed(() => state.settingsOpen)
const hallHidden = computed(() => {
  if (state.settingsOpen || showCategories.value) return true
  if (!hasGames.value) return true
  return state.page === "game"
})
const gameHidden = computed(() => {
  if (state.settingsOpen || showCategories.value) return true
  return !(state.page === "game" && hasGames.value)
})
const showEmpty = computed(() => !hasGames.value && !state.settingsOpen && !showCategories.value)

watch(() => state.settingsOpen, (open) => {
  document.body.classList.toggle("settings-open", open)
}, { immediate: true })

// 游戏页要额外压暗信息列（详见 layout.css 的 body.page-game）
watch(() => state.page, (page) => {
  document.body.classList.toggle("page-game", page === "game")
}, { immediate: true })

onMounted(() => {
  onUi("drop-hint", (on: boolean) => { dropHint.value = !!on })
  window.setTimeout(() => {
    booted.value = true
    window.setTimeout(() => document.getElementById("boot")?.remove(), 600)
  }, 260)
})
void showSettings
</script>

<style>
.boot {
  position: fixed;
  inset: 0;
  z-index: 400;
  display: grid;
  place-content: center;
  gap: 8px;
  text-align: center;
  background: var(--s-base);
  transition: opacity 0.5s var(--ease);
}
.boot.done { opacity: 0; pointer-events: none; }
.boot-logo { font-size: 26px; font-weight: 600; letter-spacing: 0.02em; }
.boot-sub { font-size: 12px; color: var(--text-3); }
</style>
