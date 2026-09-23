# 按钮模板（画廊）

使用者 2026-09-23 提供的两份按钮样式，先**存成模板**，供「按钮风格化」那一轮直接用。
样式来自开源项目、作者声明非商业免费使用 —— **具体出处链接待使用者补**（补上后写进
本文件与 `docs/theme-demos/assets/CREDITS.md` 的同一套口径里）。

| 文件 | 用途 |
| --- | --- |
| [`gallery-button.vue`](gallery-button.vue) | **展签式画廊 · 一般按钮**（启动游戏按钮除外）：浅白面 + 底部内阴影「键程」+ 悬停上浮 2px、按下沉 2px |
| [`gallery-play-button.vue`](gallery-play-button.vue) | **展签式画廊 · 启动游戏按钮**：青色实心 + 3px 实色底边 + 按下收边，标签大写字距 |
| [`preview.html`](preview.html) | 两套样式的原样预览（默认 / 悬停 / 按下三态；悬停与按下用类名模拟） |
| `preview.png` | 上面那页的 1:1 渲染图（headless Chromium 出的，方便直接看） |

## 怎么落到应用里

应用里的按钮不在 `.vue` 的 `<style scoped>` 里，而是
`layout.css` 的 `.btn` 基类 + 各主题 skin 的覆盖（画廊现在是
`gallery.skin.css` 末尾那段 `.btn.play` / `.btn.primary`）。落地时按这个顺序：

1. **一般按钮**：把模板的形状语言（浅面 + 底部内阴影 + 上下位移）搬进
   `[data-style="gallery"] .btn` / `.mini-btn` / `.menu-row` …；
   颜色与圆角换令牌（见下）。
2. **启动游戏按钮**：覆盖 `[data-style="gallery"] .btn.play`（也就是主页
   `#btnHallPlay` 与游戏页那颗），把「实色 + 底边」那套替进去。
3. 改完跑 `run_all`（主题契约的圆角/令牌守卫）与 `tools/visual.py`
   **重录主题矩阵**（按钮进了 25 张里的多张），再跑 `e2e`。

## 落地前要拍的四个点

1. **圆角与投影**：画廊现在是「1px 直角 + 无投影」（`--fx-panel-shadow: none`）。
   模板的 `border-radius: 4px/3px` 与外投影属于**抬升控件**，要么明确作为例外保留，
   要么换成 `var(--r-xs)` 并只留 `inset` 那条底边。共享层（`layout.css` / `app.css` /
   `element.css`）里写死圆角会被 `check_theme_contract.py` 拦下 —— 圆角走令牌。
2. **颜色**：模板的 `#15ccbe` / `#0f988e` 是青色，画廊现在的强调色是蓝
   （深 `#3f63e8` / 浅 `#2c4bd0`）。要么改用 `var(--a-main)` / `var(--a-2)`，
   要么确认画廊整体换青（那就不只是按钮的事）。
3. **字体**：`font-family: "Istok Web"` 应用里没有，落地换 `var(--font)` 或系统兜底；
   大写字距（`letter-spacing` + `text-transform: uppercase`）与画廊「展签印刷字」
   是同一路，可以留。
4. **尺寸与动效**：启动按钮 `width: 120px` 写死，中文「启动游戏」够用、换文案要一起调；
   它的 hover 会把文字滑出 80px、图标右移 23px —— 这是原样式的特征，落地前确认是否保留。

## 复现预览图

```powershell
$chrome = "$env:LOCALAPPDATA\ms-playwright\chromium_headless_shell-1228\chrome-headless-shell-win64\chrome-headless-shell.exe"
& $chrome --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 `
  --window-size=1200,760 --screenshot=docs\theme-templates\preview.png `
  "file:///C:/Users/HuHu1/Desktop/Tasks/v4.1/Aurora/docs/theme-templates/preview.html"
```
