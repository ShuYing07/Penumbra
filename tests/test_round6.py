# -*- coding: utf-8 -*-
"""本轮增量模块测试：数据总线 / 阴性对照 / 守卫清单 / 终端命令 / 涨跌惯例 /
组件逻辑 / 质量门控 / 事件抽取。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import numpy as np
import pandas as pd

PASS = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"[ok] {name}")


def _bars(n=200, seed=7, drift=0.0005):
    rng = np.random.default_rng(seed)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(drift, 0.02, n)))
    return pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 1e6, n)},
                        index=pd.date_range("2024-01-01", periods=n))


# ---------- 模块一：数据总线 ----------
def test_data_bus():
    from core.data_bus import reset_bus
    b = reset_bus()
    got = []
    b.subscribe("600519", lambda c, d: got.append((c, d["close"])))
    b.publish("600519", {"close": 1500.0})
    assert b.latest("600519")["ok"] is True
    assert b.latest("600519")["data"]["close"] == 1500.0
    assert ("600519", 1500.0) in got
    assert b.latest("AAPL")["ok"] is False
    assert b.stats()["snapshots"] == 1
    ok("数据总线：发布/订阅/快照/未知标的")


# ---------- 模块二：阴性对照 ----------
def test_nullius_negative_control():
    from core.quant.nullius import negative_control
    r = negative_control(_bars(), "CN", "ma_cross", None, None, n_perm=60, seed=1)
    assert "error" not in r, r
    assert 0 <= r["percentile"] <= 100
    assert r["significant"] in (True, False)
    assert "z_score" in r and "verdict" in r
    ok("阴性对照：随机信号分布对比与显著性判定")


def test_nullius_insufficient():
    from core.quant.nullius import negative_control
    r = negative_control(_bars(n=40), "CN", "ma_cross", None, None, n_perm=10)
    assert "error" in r
    ok("阴性对照：数据不足给出 error")


# ---------- 模块二：守卫清单 ----------
def test_guard_checklist():
    from core.quant.guard_checks import guard_checklist
    r = guard_checklist(_bars(n=300), "CN", "ma_cross", None, None)
    assert r["checks"], "检查清单非空"
    names = {c["name"] for c in r["checks"]}
    assert "未来函数 / 前视偏差" in names
    assert "过拟合 / 数据窥探（样本外退化）" in names
    assert "幸存者偏差（数据覆盖完整性）" in names
    assert "成交真实性（涨跌停假设 / 费用）" in names
    assert 0 <= r["score"] <= 100
    ok("守卫清单：四项检查齐全 + 评分")


# ---------- 模块四：终端命令 ----------
def test_terminal_parse():
    from app.ui.terminal_tab import parse_command
    assert parse_command("DES 600519")["action"] == "DES"
    assert parse_command("des 600519")["code"] == "600519"
    assert parse_command("GP AAPL")["code"] == "AAPL"
    assert parse_command("BT rsi")["strategy"] == "rsi"
    assert parse_command("bt boll")["strategy"] == "boll"
    assert parse_command("BT nope")["action"] == "ERR"
    assert parse_command("FOO x")["action"] == "ERR"
    assert parse_command("DES")["action"] == "ERR"
    assert parse_command("")["action"] == "EMPTY"
    assert parse_command("HELP")["action"] == "HELP"
    assert parse_command("QUIT")["action"] == "QUIT"
    ok("终端命令解析：10 种输入分支")


def test_terminal_exec_errors():
    from app.ui.terminal_tab import execute_command
    assert "未知命令" in execute_command({"action": "ERR", "error": "未知命令 FOO"})
    assert "可用命令" in execute_command({"action": "HELP", "args": [], "raw": "HELP"})
    ok("终端命令执行：错误/帮助降级")


# ---------- 模块四：涨跌惯例 ----------
def test_up_down_convention():
    from app.ui import ui_theme
    ui_theme.set_convention("a_share")
    assert ui_theme.up_color() == ui_theme.UP_A_SHARE
    assert ui_theme.down_color() == ui_theme.DOWN_A_SHARE
    assert ui_theme.get_convention() == "a_share"
    ui_theme.set_convention("global")
    assert ui_theme.up_color() == ui_theme.UP_GLOBAL
    assert ui_theme.down_color() == ui_theme.DOWN_GLOBAL
    ui_theme.set_convention("a_share")  # 恢复默认
    ok("涨跌色惯例：a_share 红涨绿跌 ↔ global 绿涨红跌")


def test_ticker_components_logic():
    from app.ui.ticker_components import _chg_color, _fmt
    assert _chg_color(1.5) == "#FF5252" and _chg_color(-1.5) == "#26A69A"
    assert _fmt(3.14159) == "3.14" and _fmt(None) == "—"
    ok("金融组件：涨跌色与数字格式化")


# ---------- 模块五：质量门控 ----------
def test_quality_gate():
    from core.agents.analyst_team import quality_gate
    good = {"technical": {"stance": "看多", "confidence": 0.7, "view": "趋势向上",
                          "key_points": ["a"], "risks": []}}
    bad_conf = {"news": {"stance": "中性", "confidence": 0.1, "view": "无"}}
    bad_missing = {"sentiment": {"stance": "看多"}}  # 缺 confidence/view
    bad_shape = {"macro": "字符串输出"}
    r = quality_gate({**good, **bad_conf, **bad_missing, **bad_shape},
                     min_confidence=0.3)
    assert r["passed_keys"] == ["technical"]
    assert len(r["gated"]) == 3
    assert r["report"] == "1 通过 / 3 剔除"
    ok("质量门控：剔除缺字段/低置信度/非结构化信号")


# ---------- 模块五：事件抽取 ----------
def test_event_extractor():
    from memory.event_extractor import (extract_event_type,
                                        link_event_to_entity,
                                        link_events_batch)
    assert extract_event_type("茅台业绩预增，净利润增长15%")[0] == "业绩预增"
    assert extract_event_type("股东减持套现")[0] == "股东减持"
    assert extract_event_type("收到政策补贴")[0] == "政策补贴"
    assert extract_event_type("日常经营正常")[0] == "其他事件"
    r = link_event_to_entity("600519", "贵州茅台业绩预增")
    assert r["linked"] and r["event_type"] == "业绩预增" and r["relations"] == 1
    b = link_events_batch("600519", ["中标重大合同", "日常经营正常"], industry="白酒")
    assert b["total_relations"] >= 2  # 1 事件链 + 1 行业链
    ok("事件抽取：类型识别 + 传导链入库 + 行业联动")


if __name__ == "__main__":
    test_data_bus()
    test_nullius_negative_control()
    test_nullius_insufficient()
    test_guard_checklist()
    test_terminal_parse()
    test_terminal_exec_errors()
    test_up_down_convention()
    test_ticker_components_logic()
    test_quality_gate()
    test_event_extractor()
    print(f"\nALL PASS ({PASS})")
