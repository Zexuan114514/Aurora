/* Aurora 前端 · 桥接调用层（P4.1）
 *
 * 页面通过 pywebview 暴露的 `window.pywebview.api` 调后端。全前端只有这一处
 * 直接摸桥接对象，其它模块一律 `import { call } from "./core/api.js"` ——
 * 这样「谁在调后端」永远只有一个出口，也方便统一做错误上报。
 */

/** 桥接对象（pywebview 注入）；没就绪时返回 null。 */
export const bridge = () => (window.pywebview && window.pywebview.api) || null;

/** 桥接是否可用（启动期轮询用）。 */
export const bridgeReady = () => !!bridge();

/** 调一个后端方法；方法不存在就抛错，交给调用方处理。 */
export const call = async (name, ...args) => {
  const api = bridge();
  if (!api || typeof api[name] !== "function") throw new Error("bridge not ready");
  return api[name](...args);
};
