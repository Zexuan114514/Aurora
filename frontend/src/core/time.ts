/** Aurora v2 · 时间格式化（v1 core/time.js 原样迁移）。 */

/** 游玩时长：秒 → 「1.5 小时」/「23 分钟」/「不到 1 分钟」。 */
export const hours = (sec: number): string => {
  if (sec >= 3600) return (sec / 3600).toFixed(sec >= 36000 ? 0 : 1) + " 小时"
  const minutes = Math.round(sec / 60)
  return minutes < 1 ? "不到 1 分钟" : minutes + " 分钟"
}

/** 运行中的实时计时：00:35 / 1:02:03。 */
export const clock = (sec: number): string => {
  const total = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, "0")
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

/** 本次会话已经玩了多久（秒）；没在跑就是 0。 */
export const sessionSeconds = (game?: { session_started_at?: number } | null): number =>
  game?.session_started_at ? Math.floor(Date.now() / 1000) - game.session_started_at : 0

/** 会话历史里的时间戳（秒）→ 2026-09-15 21:30。 */
export const stamp = (ts?: number): string => {
  if (!ts) return "—"
  const d = new Date(Number(ts) * 1000)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
