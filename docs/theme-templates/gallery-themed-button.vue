<!-- 展签式画廊 · 一般 / 确认 / 启动按钮模板。应用皮肤与本模板共用 CSS。 -->
<script setup lang="ts">
defineOptions({ inheritAttrs: false })
withDefaults(defineProps<{
  variant?: 'default' | 'primary' | 'play'
  mode?: 'dark' | 'light'
  disabled?: boolean
  running?: boolean
}>(), { variant: 'default', mode: 'light', disabled: false, running: false })
</script>

<template>
  <span class="button-template" data-style="gallery" :data-theme="mode">
    <button v-bind="$attrs" class="btn" :class="{ primary: variant === 'primary', play: variant === 'play', running }"
      type="button" :disabled="disabled">
      <slot>{{ variant === 'play' ? (running ? '结束游戏' : '开始游戏') : variant === 'primary' ? '保存设置' : '背景图' }}</slot>
    </button>
  </span>
</template>

<style src="../../frontend/src/styles/themes/gallery.buttons.skin.css"></style>
<style scoped>
.button-template { display: inline-flex; --font: "Segoe UI", "Microsoft YaHei UI", sans-serif; }
:where(.button-template .btn) {
  box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; height: 40px; padding: 0 18px; font-size: 14px; font-weight: 560;
  white-space: nowrap; cursor: pointer; border-radius: var(--r-md);
}
:where(.button-template .btn.play) { height: 46px; padding-inline: 26px; font-size: 15px; }
/* :where 让示例几何不盖过同一份主题皮肤。Atelier 的印章需要 56px 高。 */
.button-template[data-style="gallery"] {
  --s-panel: #262c35;
  --s-elevated: #2f3640;
  --text-1: #ffffff;
  --a-main: #3f63e8;
  --a-2: #c9ced8;
  --a-on: #ffffff;
  --r-md: 1px;
  --r-xs: 1px;
  --r-pill: 1px;
  --font: "Times New Roman", "Songti SC", "SimSun", "Source Han Serif SC", Georgia, serif;
}
.button-template[data-style="gallery"][data-theme="light"] {
  --s-panel: #fdfcfa;
  --s-elevated: #fdfcfa;
  --text-1: #0e0f12;
  --a-main: #2c4bd0;
  --a-2: #5a6478;
  --a-on: #ffffff;
  --r-md: 1px;
  --r-xs: 1px;
  --r-pill: 1px;
}
</style>
