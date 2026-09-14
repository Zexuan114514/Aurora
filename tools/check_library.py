"""检查用户现有游戏库是否完好。"""
from __future__ import annotations

import json
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "data" / "library.json"
d = json.loads(p.read_text(encoding="utf-8"))
print("游戏数:", len(d["games"]))
for g in d["games"]:
    src = g.get("data_source") or ("steam" if g.get("appid") else "-")
    sid = g.get("source_id") or g.get("appid") or "-"
    print(f"  {g.get('name')}   [{src}:{sid}]  图片 {len(g.get('images') or [])} 张")
cfg = (d.get("settings") or {}).get("sources")
print("资料源配置:", json.dumps(cfg, ensure_ascii=False) if cfg else "(默认)")
