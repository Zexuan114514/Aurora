<!-- 收藏架 · 一般 / 确认 / 启动按钮模板。应用皮肤与本模板共用 CSS。 -->
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
  <span class="button-template" data-style="shelf" :data-theme="mode">
    <button v-bind="$attrs" class="btn" :class="{ primary: variant === 'primary', play: variant === 'play', running }"
      type="button" :disabled="disabled">
      <slot>{{ variant === 'play' ? (running ? '结束游戏' : '开始游戏') : variant === 'primary' ? '保存设置' : '背景图' }}</slot>
    </button>
  </span>
</template>

<style src="../../frontend/src/styles/themes/shelf.buttons.skin.css"></style>
<style scoped>
.button-template { display: inline-flex; --font: "Segoe UI", "Microsoft YaHei UI", sans-serif; }
:where(.button-template .btn) {
  box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; height: 40px; padding: 0 18px; font-size: 14px; font-weight: 560;
  white-space: nowrap; cursor: pointer; border-radius: var(--r-md);
}
:where(.button-template .btn.play) { height: 46px; padding-inline: 26px; font-size: 15px; }
/* :where 让示例几何不盖过同一份主题皮肤。Atelier 的印章需要 56px 高。 */
.button-template[data-style="shelf"] {
  --s-panel: #3a2f22;
  --s-elevated: #463a2a;
  --text-1: #ede7dd;
  --a-main: #c8a24a;
  --a-2: #8c6b3f;
  --a-on: #1a1509;
  --r-md: 4px;
  --r-xs: 2px;
  --r-pill: 3px;
  --font: "KaiTi", "Songti SC", "SimSun", Georgia, "Microsoft YaHei", serif;
}
.button-template[data-style="shelf"][data-theme="light"] {
  --s-panel: #fdf8f4;
  --s-elevated: #fdf8f4;
  --text-1: #1b1712;
  --a-main: #9a7a2e;
  --a-2: #a8857f;
  --a-on: #fbf7f0;
  --r-md: 4px;
  --r-xs: 2px;
  --r-pill: 3px;
}
</style>
