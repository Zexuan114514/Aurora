<!-- 展签式画廊 · 「启动游戏」按钮
     ------------------------------------------------------------------
     来源：使用者 2026-09-23 提供（开源项目样式，非商业免费使用；出处链接待补）。
     特征：青色实心 + 3px 实色底边（`0 3px 0 #0f988e`）造出「压得下去的键」，
     按下时整体下移 3px 并把底边收掉；标签走大写字距（与画廊「展签印刷字」同调）。
     落地注意：
       * 强调色 `#15ccbe` / `#0f988e` 是青色，与画廊现有蓝（`--a-main`）冲突 ——
         要么改用 `var(--a-main)` / `var(--a-2)`，要么确认画廊换青；
       * `font-family: "Istok Web"` 应用里没装，落地换 `var(--font)` 或系统兜底；
       * `width: 120px` 是写死的：中文「启动游戏」四个字够用，换文案要一起调；
       * hover 会把 `.text` 右移 80px、`.icon` 右移 23px（`overflow: hidden` 下
         文字滑出、只留图标）—— 这是原样式的一部分，落地前先确认要不要保留。
     ------------------------------------------------------------------ -->
<style scoped>
  .button-with-icon {
    overflow: hidden;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid #0f988e;
    font-family: "Istok Web", sans-serif;
    letter-spacing: 1px;
    padding: 0 12px;
    text-align: center;
    width: 120px;
    height: 40px;
    font-size: 14px;
    text-transform: uppercase;
    font-weight: normal;
    border-radius: 3px;
    outline: none;
    user-select: none;
    cursor: pointer;
    transform: translateY(0px);
    position: relative;
    box-shadow:
      inset 0 30px 30px -15px rgba(255, 255, 255, 0.1),
      inset 0 0 0 1px rgba(255, 255, 255, 0.3),
      inset 0 1px 20px rgba(0, 0, 0, 0),
      0 3px 0 #0f988e,
      0 3px 2px rgba(0, 0, 0, 0.2),
      0 5px 10px rgba(0, 0, 0, 0.1),
      0 10px 20px rgba(0, 0, 0, 0.1);
    background: #15ccbe;
    color: white;
    text-shadow: 0 1px 0 rgba(0, 0, 0, 0.3);
    transition: 150ms all ease-in-out;
  }

  .button-with-icon .icon {
    margin-right: 8px;
    width: 24px;
    height: 24px;
    transition: all 0.5s ease-in-out;
  }

  .button-with-icon:active {
    transform: translateY(3px);
    box-shadow:
      inset 0 16px 2px -15px rgba(0, 0, 0, 0),
      inset 0 0 0 1px rgba(255, 255, 255, 0.15),
      inset 0 1px 20px rgba(0, 0, 0, 0.1),
      0 0 0 #0f988e,
      0 0 0 2px rgba(255, 255, 255, 0.5),
      0 0 0 rgba(0, 0, 0, 0),
      0 0 0 rgba(0, 0, 0, 0);
  }

  .button-with-icon:hover .text {
    transform: translateX(80px);
  }

  .button-with-icon:hover .icon {
    transform: translate(23px);
  }

  .text {
    transition: all 0.5s ease-in-out;
  }
</style>

<template>
  <button class="button-with-icon">
    <svg
      class="icon"
      id="Play"
      viewBox="0 0 48 48"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        class="color000000 svgShape"
        fill="#ffffff"
        d="M12 39c-.549 0-1.095-.15-1.578-.447A3.008 3.008 0 0 1 9 36V12c0-1.041.54-2.007 1.422-2.553a3.014 3.014 0 0 1 2.919-.132l24 12a3.003 3.003 0 0 1 0 5.37l-24 12c-.42.21-.885.315-1.341.315z"
      ></path>
    </svg>
    <span class="text">Play</span>
  </button>
</template>
