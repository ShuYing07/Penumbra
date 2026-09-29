# -*- coding: utf-8 -*-
"""模块五：实时行情引擎测试。"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.realtime_engine import RealtimeEngine, _BACKOFF_BASE

# 1) 退避序列
assert _BACKOFF_BASE == [1, 2, 4, 8, 16, 30]
assert min(0, 5) == 0 and min(7, 5) == 5
print("[ok] 退避序列:", _BACKOFF_BASE)

# 2) 引擎生命周期（mock 下 get_realtime 走缓存/降级，不崩）
eng = RealtimeEngine(interval=2)
quotes, statuses = [], []


def _q(q, ts):
    quotes.append(q)


def _s(text):
    statuses.append(text)
    print("  status:", text)


eng.on_quotes, eng.on_status = _q, _s
eng.start(["SH600519", "AAPL", "0700.HK"])
# 轮询等待首批行情（首轮可能因首次 import 变慢）
deadline = time.time() + 15
while not quotes and time.time() < deadline:
    time.sleep(0.5)
assert quotes, "15s 内未收到任何行情批次"
assert eng.running is True
eng.stop()
assert eng.running is False
print(f"[ok] 引擎生命周期：收到 {len(quotes)} 批行情，状态 {len(statuses)} 条")

# 3) 无标的自检
eng2 = RealtimeEngine()
s2: list[str] = []
eng2.on_status = lambda text: s2.append(text)
eng2.start([])
assert any("无订阅标的" in t for t in s2), s2
eng2.stop()
print("[ok] 空订阅防护")

# 4) WS 解析（外部消息格式）
import json as _json
eng3 = RealtimeEngine()
out = []
msg = _json.dumps({"code": "SH600519", "price": 1500.5, "chg_pct": 1.2})
eng3.on_quotes = lambda q, ts: out.append(q)
eng3._handle_ws_msg(msg)
assert out and out[0][0]["code"] == "SH600519" and out[0][0]["price"] == 1500.5
eng3._handle_ws_msg("SH600519=1500.5,1.2; AAPL=210.0,-0.5")
assert len(out) == 2 and out[1][1]["code"] == "AAPL"
print("[ok] WebSocket 消息解析（JSON + 行格式）")

print("\nALL PASS")
