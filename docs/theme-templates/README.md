# 主题按钮模板

## 当前版本：五套主题按钮（P8.19，2026-09-24）

五个 Vue 单文件组件均支持一般、确认、启动三种按钮，以及运行中、禁用状态。
它们直接引用应用的 `<theme>.buttons.skin.css`，模板和应用共用一份按钮实现。
组件内仅补独立预览需要的主题令牌与基础尺寸；应用继续使用现有按钮 DOM 和事件。

| 主题 | Vue 模板 | 一般按钮 | 启动按钮 |
| --- | --- | --- | --- |
| 极光玻璃 | [aurora-themed-button.vue](aurora-themed-button.vue) | 薄边玻璃胶囊 | 青紫折射边与一条高光，悬停轻抬 |
| 展签式画廊 | [gallery-themed-button.vue](gallery-themed-button.vue) | 直角墨线展签 | 强调色双框，悬停内框收紧；无外投影 |
| 夜间放映厅 | [screening-themed-button.vue](screening-themed-button.vue) | 琥珀底线、窄体排印 | 指示灯与底边胶片刻度，悬停点亮 |
| 收藏架 | [shelf-themed-button.vue](shelf-themed-button.vue) | 黄铜细边、纸面压线 | 书脊双线，悬停向右抽出 2px |
| Atelier 工作台 | [atelier-themed-button.vue](atelier-themed-button.vue) | 虚线纸签 | 椭圆双圈印章，轻微倾斜，悬停回正 |

可直接打开 [交互预览](preview-themes.html)，或查看 [深浅模式总览](preview-themes.png)。
预览与应用一样保留 hover / active / focus-visible；使用 Tab 检查焦点。

```vue
<script setup lang="ts">
import GalleryButton from './gallery-themed-button.vue'
</script>

<template>
  <GalleryButton mode="light" @click="openBackgrounds">背景图</GalleryButton>
  <GalleryButton mode="light" variant="primary" @click="save">保存设置</GalleryButton>
  <GalleryButton mode="light" variant="play" :running="running" @click="toggleGame" />
  <GalleryButton mode="light" disabled>暂不可用</GalleryButton>
</template>
```

`mode` 为 `light | dark`（默认 light），`variant` 为 `default | primary | play`。
文案可由 slot 覆盖，原生事件、title、aria-label 等属性转交内部 button。
组件应使用唯一的外部标签说明操作；示例里的业务函数由使用方提供。

### 应用接入与验收约定

- 实现位于 `frontend/src/styles/themes/<theme>.buttons.skin.css`，五张皮肤均不超过 200 行。
- `app.css` 在主题签名、布局、Element Plus 桥接之后导入按钮皮肤；旧签名文件中的按钮覆盖已迁出。
- `.btn` / `.mini-btn` 是一般操作，`.btn.primary` 是确认，`.btn.play` 覆盖大厅和详情页启动键。
- 保留现有 id、事件、文案和布局定位。装饰伪元素仅限启动键，且不接收鼠标事件。
- 字体、强调色来自主题令牌。浅色态主按钮底色压暗到强调色的 80%，使白字具有足够余量。
  薄荷青、樱花粉、琥珀橙三种强调色覆盖使用深墨字；运行中退为中性描边。
- 无常驻动画；开启系统「减少动态效果」后，按钮位移与过渡关闭。
- Atelier 启动印章为 56px 高的椭圆，确认按钮仍为方形纸片。避免把大印章铺进设置行或弹窗。

模板已通过 Vue SFC 编译检查。五主题 × 深浅 × 四种强调色 × 四种状态 × 四类可用按钮，
共 **640 个文字对比度采样全部 ≥4.5，最低 4.94**；禁用态不参与正文对比度验收。
完整的应用验收与真窗口检查记录见 [P8.19 交付记录](../architecture/p8-frontend-v2.md)。

## 历史存档：P8.16 画廊按钮试验（已撤回）

以下两份原始 Uiverse 模板及其旧预览保留作参考；下文的「落地口径」描述的是当时版本，
当前实现以本页上方的 P8.19 为准。

使用者 2026-09-23 提供的两份按钮样式（来自 Uiverse，均为 **MIT License**）。
它们曾按下面的四条口径落进画廊主题（P8.16），但**使用者实机看着「观感不如改动前」，
2026-09-24 凌晨已把应用里的那版皮肤下线**（`gallery.buttons.skin.css` 删除、
`#btnHallPlay` 恢复纯文字、主题基线回滚并复跑 25/25 偏差 0）。
这里保留原样样式与三态预览作为模板与对照 —— **按钮风格化的当前实现以 P8.19 为准，
本节只记录 P8.16 的撤回教训**。

下次开工前先读这页最后那节「这次的教训」。

## 出处

| 模板 | 出处 | 作者 | 许可 |
| --- | --- | --- | --- |
| `gallery-button.vue` | [uiverse.io/TCdesign-dev/short-lizard-47](https://uiverse.io/TCdesign-dev/short-lizard-47) | TCdesign-dev（Custyyyy，2022-01-07） | MIT License |
| `gallery-play-button.vue` | [uiverse.io/elijahgummer/proud-goat-69](https://uiverse.io/elijahgummer/proud-goat-69) | elijahgummer（Elijah W Gummer） | MIT License |

> Uiverse 页面直接抓取会返回 403，上面两条是用浏览器 UA 取的；两份的许可行都写着
> `MIT License` + `Copyright - …`。原样样式只在 `docs/` 里存档与对照，应用里用的是
> 下面「落地口径」改写过的版本（换令牌、换字体）。

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

## 落地口径（使用者 2026-09-23 拍板）

1. **保留按钮原貌** —— 尺寸、圆角（4px / 3px）、三层投影、±2px 位移、按下收边全部照搬；
   画廊其余界面仍是「1px 直角 + 无投影」，这两个按钮是**有意的例外**（在皮肤文件头写明）。
2. **颜色跟强调色** —— 启动按钮原来的青 `#15ccbe` / `#0f988e` 换成 `--a-main` 与
   「同色压暗 26%」（`color-mix(in srgb, var(--a-main) 74%, #000)`，原样式的
   `#15ccbe → #0f988e` 正是这个比例）；文字 `--a-on`。一般按钮的浅面 / 墨色 / 键程底边
   换成 `--s-elevated` / `--text-1` / `--ln140`。
3. **字体跟主题** —— `"Istok Web"` → `var(--font)`（画廊是衬线那一档）。
4. **尺寸与动效先保留** —— `width: 120px` 与 hover「文字滑出 80px、图标补位」都留着。

代码落在 [`gallery.buttons.skin.css`](../../frontend/src/styles/themes/gallery.buttons.skin.css)：
这一轮同时把主题契约放宽成「**一套主题可以有多张皮肤**」（守卫与 `themes.spec.ts` 都
按 `<theme>*.skin.css` 逐张查行数与作用域），按钮语言因此单开一张，别写进主题签名那张
（它已经 198/200 行）。

## 当时列的四个待拍点（已按上面口径处理）

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

## 这次的教训（撤回之后补写）

1. **两套样式本身没问题，问题是它们和画廊的整体语言打架**：画廊是「1px 直角 + 无投影 +
   只有细线」，而这两颗按钮是「4px/3px 圆角 + 多层投影 + 位移」的**抬升控件**。
   单独看好看，放进满屏细线里就显脏 —— 使用者实机的原话是「观感不如改动前」。
   下次要么**只挑一颗**（比如只做主 CTA）先在真机上看两天，要么先把圆角/投影这两条
   与画廊对齐，再保留剩下的特征。
2. **整张皮肤一起上线，风险面太大**：`gallery.buttons.skin.css` 一上线就同时改了
   `.btn` 全体 + `.mini-btn` + `.btn.play`。撤回时是整文件下线才回到原状的
   （基线复跑 25/25 偏差 0 可证）。下次按「一颗按钮一条规则」小步走。
3. **hover 那套动效要单独确认**：文字滑出 80px 后再看，屏幕上只剩图标，中文四个字
   在 120px 里滑出去的过程比预览图里明显得多 —— 这类「原样式的特征」在真机上的观感
   和静态预览差别很大。
