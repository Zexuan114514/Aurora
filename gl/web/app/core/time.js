/* Aurora 前端 · 时间格式化（P4.3-k）
 *
 * 从主模块搬出来的几个纯函数：游玩时长、运行中的时钟、本次会话秒数、
 * 会话历史时间戳。大厅底部信息带、游戏页信息条、详情面板与实时计时都要用，
 * 所以单独成一块（视图模块也 import 得到，不必再往 ctx 里塞）。
 */

/** 游玩时长：秒 → 「1.5 小时」/「23 分钟」/「不到 1 分钟」。 */
export const hours = (sec) => {
  if (sec >= 3600) return (sec / 3600).toFixed(sec >= 36000 ? 0 : 1) + " 小时";
  const minutes = Math.round(sec / 60);
  return minutes < 1 ? "不到 1 分钟" : minutes + " 分钟";
};

/** 运行中的实时计时：00:35 / 1:02:03。 */
export const clock = (sec) => {
  const total = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
};

/** 本次会话已经玩了多久（秒）；没在跑就是 0。 */
export const sessionSeconds = (game) =>
  game.session_started_at ? Math.floor(Date.now() / 1000) - game.session_started_at : 0;

/** 会话历史里的时间戳（秒）→ 2026-09-15 21:30。 */
export const stamp = (ts) => {
  const d = new Date((Number(ts) || 0) * 1000);
  if (!ts) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
