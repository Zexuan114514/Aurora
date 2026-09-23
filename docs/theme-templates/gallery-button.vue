<!-- 展签式画廊 · 一般按钮（启动游戏按钮除外）
     ------------------------------------------------------------------
     来源：使用者 2026-09-23 提供（开源项目样式，非商业免费使用；出处链接待补）。
     配色特征 `#d6d6e7` + `rgba(45, 35, 66, …)` 与常见的 3D 抬升按钮一脉相承。
     落地注意：画廊现有语言是「1px 直角 + 无投影」——
       * `border-radius: 4px` / 外投影属于**抬升控件**，要么作为例外明确保留，
         要么换成 `var(--r-xs)` + 只留 `inset` 那条底边；
       * 颜色建议接令牌：`#fcfcfd` → `--s-elevated`、`#36395a` → `--text-1`、
         `#d6d6e7` → `--ln140` 一档。
     ------------------------------------------------------------------ -->
<style scoped>
  .button-name {
    align-items: center;
    appearance: none;
    background-color: #fcfcfd;
    border-radius: 4px;
    border-width: 0;
    box-shadow:
      rgba(45, 35, 66, 0.2) 0 2px 4px,
      rgba(45, 35, 66, 0.15) 0 7px 13px -3px,
      #d6d6e7 0 -3px 0 inset;
    box-sizing: border-box;
    color: #36395a;
    cursor: pointer;
    display: inline-flex;
    height: 48px;
    justify-content: center;
    line-height: 1;
    list-style: none;
    overflow: hidden;
    padding-left: 16px;
    padding-right: 16px;
    position: relative;
    text-align: left;
    text-decoration: none;
    transition:
      box-shadow 0.15s,
      transform 0.15s;
    user-select: none;
    -webkit-user-select: none;
    touch-action: manipulation;
    white-space: nowrap;
    will-change: box-shadow, transform;
    font-size: 18px;
  }

  .button-name:focus {
    box-shadow:
      #d6d6e7 0 0 0 1.5px inset,
      rgba(45, 35, 66, 0.4) 0 2px 4px,
      rgba(45, 35, 66, 0.3) 0 7px 13px -3px,
      #d6d6e7 0 -3px 0 inset;
  }

  .button-name:hover {
    box-shadow:
      rgba(45, 35, 66, 0.3) 0 4px 8px,
      rgba(45, 35, 66, 0.2) 0 7px 13px -3px,
      #d6d6e7 0 -3px 0 inset;
    transform: translateY(-2px);
  }

  .button-name:active {
    box-shadow: #d6d6e7 0 3px 7px inset;
    transform: translateY(2px);
  }
</style>

<template>
  <button class="button-name" role="button">Button-name</button>
</template>
