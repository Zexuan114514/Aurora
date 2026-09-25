<!-- Atelier 工作台 · 一般 / 确认 / 启动按钮模板。应用皮肤与本模板共用 CSS。 -->
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
  <span class="button-template" data-style="atelier" :data-theme="mode">
    <button v-bind="$attrs" class="btn" :class="{ primary: variant === 'primary', play: variant === 'play', running }"
      type="button" :disabled="disabled">
      <slot>{{ variant === 'play' ? (running ? '结束游戏' : '开始游戏') : variant === 'primary' ? '保存设置' : '背景图' }}</slot>
    </button>
  </span>
</template>

<style src="../../frontend/src/styles/themes/atelier.buttons.skin.css"></style>
<style scoped>
.button-template { display: inline-flex; --font: "Segoe UI", "Microsoft YaHei UI", sans-serif; }
:where(.button-template .btn) {
  box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; height: 40px; padding: 0 18px; font-size: 14px; font-weight: 560;
  white-space: nowrap; cursor: pointer; border-radius: var(--r-md);
}
:where(.button-template .btn.play) { height: 46px; padding-inline: 26px; font-size: 15px; }
/* :where 让示例几何不盖过同一份主题皮肤。Atelier 的印章需要 56px 高。 */
.button-template[data-style="atelier"] {
  --s-panel: #443540;
  --s-elevated: #4f3e49;
  --text-1: #f6ecf0;
  --a-main: #e08aa4;
  --a-2: #b8506c;
  --a-on: #2a141b;
  --r-md: 2px;
  --r-xs: 2px;
  --r-pill: 2px;
  --font: "KaiTi", "Songti SC", "SimSun", "Source Han Serif SC", Georgia, serif;
}
.button-template[data-style="atelier"][data-theme="light"] {
  --s-panel: #fffdfb;
  --s-elevated: #fffdfb;
  --text-1: #3b2f36;
  --a-main: #b8506c;
  --a-2: #d4738e;
  --a-on: #fff8fa;
  --r-md: 2px;
  --r-xs: 2px;
  --r-pill: 2px;
}
</style>
