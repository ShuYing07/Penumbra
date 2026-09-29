# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.daily_briefing import (build_briefing, briefing_path, push_feishu,
                                 push_email, push_channels, configured_channels)

# 未配置渠道 → 优雅降级
assert not configured_channels(), configured_channels()
r1 = push_feishu("test")
assert r1["ok"] is False and "未配置" in r1["note"], r1
r2 = push_email("x", "y")
assert r2["ok"] is False, r2
print("[ok] 未配置渠道优雅跳过")

# 简报生成
from datetime import datetime
html = build_briefing(datetime(2026, 9, 29, 7, 30))
path = briefing_path("2026-09-29")
assert os.path.exists(path)
md = open(path, encoding="utf-8").read()
assert "疏影·知微 每日市场简报" in md and "不构成任何投资建议" in md
print("[ok] 简报生成:", path, f"({len(md)}B)")

# 多渠道总入口不抛异常
results = push_channels(path, html)
assert isinstance(results, list) and len(results) == 2
print("[ok] push_channels 返回:", results)
print("\nALL PASS")
