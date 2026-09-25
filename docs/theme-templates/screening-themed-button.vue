<!-- 夜间放映厅 · 一般 / 确认 / 启动按钮模板。应用皮肤与本模板共用 CSS。 -->
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
  <span class="button-template" data-style="screening" :data-theme="mode">
    <button v-bind="$attrs" class="btn" :class="{ primary: variant === 'primary', play: variant === 'play', running }"
      type="button" :disabled="disabled">
      <slot>{{ variant === 'play' ? (running ? '结束游戏' : '开始游戏') : variant === 'primary' ? '保存设置' : '背景图' }}</slot>
    </button>
  </span>
</template>

<style src="../../frontend/src/styles/themes/screening.buttons.skin.css"></style>
<style scoped>
.button-template { display: inline-flex; --font: "Segoe UI", "Microsoft YaHei UI", sans-serif; }
:where(.button-template .btn) {
  box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; height: 40px; padding: 0 18px; font-size: 14px; font-weight: 560;
  white-space: nowrap; cursor: pointer; border-radius: var(--r-md);
}
:where(.button-template .btn.play) { height: 46px; padding-inline: 26px; font-size: 15px; }
/* :where 让示例几何不盖过同一份主题皮肤。Atelier 的印章需要 56px 高。 */
.button-template[data-style="screening"] {
  --s-panel: #1c1209;
  --s-elevated: #26190d;
  --text-1: #f8f0e4;
  --a-main: #e9a13b;
  --a-2: #d08a4a;
  --a-on: #1a1409;
  --r-md: 3px;
  --r-xs: 2px;
  --r-pill: 2px;
  --font: "Bahnschrift SemiCondensed", "Arial Narrow", "Microsoft YaHei UI",
          "Microsoft YaHei", sans-serif;
}
.button-template[data-style="screening"][data-theme="light"] {
  --s-panel: #fffaf1;
  --s-elevated: #fffaf1;
  --text-1: #201a12;
  --a-main: #b4761f;
  --a-2: #8a5b1c;
  --a-on: #fffaf1;
  --r-md: 3px;
  --r-xs: 2px;
  --r-pill: 2px;
}
</style>
