import { describe, expect, it, vi } from "vitest"

import { clock, hours, sessionSeconds, stamp } from "@/core/time"

describe("时间格式化", () => {
  it("hours：小时 / 分钟 / 不到一分钟", () => {
    expect(hours(0)).toBe("不到 1 分钟")
    expect(hours(20)).toBe("不到 1 分钟")
    // v1 的口径：四舍五入到分钟，所以 59 秒会显示成「1 分钟」（判据冻结，不改行为）
    expect(hours(59)).toBe("1 分钟")
    expect(hours(60)).toBe("1 分钟")
    expect(hours(3600)).toBe("1.0 小时")
    expect(hours(36000)).toBe("10 小时")
  })

  it("clock：一小时以内 mm:ss，超过 h:mm:ss", () => {
    expect(clock(0)).toBe("00:00")
    expect(clock(35)).toBe("00:35")
    expect(clock(3723)).toBe("1:02:03")
    expect(clock(-5)).toBe("00:00")
  })

  it("sessionSeconds：没在跑就是 0，在跑就是与现在的差值", () => {
    expect(sessionSeconds(null)).toBe(0)
    expect(sessionSeconds({})).toBe(0)
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-09-22T10:00:00Z"))
    const now = Math.floor(Date.now() / 1000)
    expect(sessionSeconds({ session_started_at: now - 90 })).toBe(90)
    vi.useRealTimers()
  })

  it("stamp：空值给破折号，否则 YYYY-MM-DD HH:mm", () => {
    expect(stamp(0)).toBe("—")
    expect(stamp(1758326400)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
  })
})
