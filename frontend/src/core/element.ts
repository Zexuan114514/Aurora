/**
 * Element Plus 按需注册的唯一入口。
 *
 * 模板里写 `<el-tooltip>` / `<el-switch>` / `<el-slider>`，Vue 会把
 * kebab-case 映射回这里的组件名，所以不需要 `app.use(ElementPlus)`。
 *
 * 只注册用得到的组件（样式在 `@/styles/element-plus.css`）：组件库的
 * 样式和行为仍然是它自己的，主题靠 `--el-*` 桥接（`@/styles/element.css`）。
 */
import { ElButton, ElInput, ElSlider, ElSwitch, ElTooltip } from "element-plus"
import type { App } from "vue"

const COMPONENTS = { ElTooltip, ElSwitch, ElSlider, ElButton, ElInput }

export function installElement(app: App): void {
  for (const [name, component] of Object.entries(COMPONENTS)) {
    app.component(name, component as Parameters<App["component"]>[1])
  }
}
