<!-- 极光玻璃 · 一般 / 确认 / 启动按钮模板。应用皮肤与本模板共用 CSS。 -->
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
  <span class="button-template" data-style="aurora" :data-theme="mode">
    <button v-bind="$attrs" class="btn" :class="{ primary: variant === 'primary', play: variant === 'play', running }"
      type="button" :disabled="disabled">
      <slot>{{ variant === 'play' ? (running ? '结束游戏' : '开始游戏') : variant === 'primary' ? '保存设置' : '背景图' }}</slot>
    </button>
  </span>
</template>

<style src="../../frontend/src/styles/themes/aurora.buttons.skin.css"></style>
<style scoped>
.button-template { display: inline-flex; --font: "Segoe UI", "Microsoft YaHei UI", sans-serif; }
:where(.button-template .btn) {
  box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; height: 40px; padding: 0 18px; font-size: 14px; font-weight: 560;
  white-space: nowrap; cursor: pointer; border-radius: var(--r-md);
}
:where(.button-template .btn.play) { height: 46px; padding-inline: 26px; font-size: 15px; }
/* :where 让示例几何不盖过同一份主题皮肤。Atelier 的印章需要 56px 高。 */
.button-template[data-style="aurora"] {
  --s-panel: #0c1622;
  --s-elevated: #121e2c;
  --text-1: #ffffff;
  --a-main: #4fd6c4;
  --a-2: #8b7cff;
  --a-on: #04211f;
  --r-md: 16px;
  --r-xs: 8px;
  --r-pill: 999px;
}
.button-template[data-style="aurora"][data-theme="light"] {
  --s-panel: #ffffff;
  --s-elevated: #ffffff;
  --text-1: #14161d;
  --a-main: #0f9e90;
  --a-2: #6c5ce0;
  --a-on: #ffffff;
  --r-md: 16px;
  --r-xs: 8px;
  --r-pill: 999px;
}
</style>
