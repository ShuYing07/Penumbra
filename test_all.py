# -*- coding: utf-8 -*-
"""端到端自动化冒烟测试（离线优先，网络项用缓存/mock，不真调 LLM）。

运行：python test_all.py
退出码 0 = 全部通过。
"""
from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"PASS  {name}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"FAIL  {name}\n      {type(e).__name__}: {e}")
        traceback.print_exc(limit=1)


# ---------- 1. 数据获取 ----------
def t_daily():
    import pandas as pd
    from core.data import service
    df, src = service.get_daily("SH600519")
    assert len(df) > 0, "日线为空"
    for c in ("open", "high", "low", "close", "volume"):
        assert c in df.columns, f"缺列 {c}"
    assert df["close"].notna().any(), "close 全空"

def t_realtime():
    from core.data import service
    r = service.get_realtime("SH600519")
    assert r.get("price") and r["price"] > 0, f"价格无效 {r}"


# ---------- 2. 技术指标 ----------
def t_indicators():
    import numpy as np
    import pandas as pd
    from core.quant import indicators as ind
    n = 120
    close = pd.Series(100 + np.cumsum(np.random.randn(n)), dtype=float)
    high = close * 1.01; low = close * 0.99
    rsi = ind.rsi(close); macd, sig, hist = ind.macd(close)
    b = ind.boll(close); k, d, j = ind.kdj(high, low, close)
    assert rsi.notna().any(), "RSI 全空"
    assert len(macd) == n and len(b[0]) == n, "指标长度不对"
    assert k.notna().any() and d.notna().any(), "KDJ 空"


# ---------- 3. 合规过滤 ----------
def t_compliance():
    from core.compliance import sanitize_ai_output
    out1 = sanitize_ai_output("建议买入贵州茅台")
    assert "【已过滤】" in out1 and "买入" not in out1, out1
    out2 = sanitize_ai_output("该股票目标价100元")
    assert "目标价" not in out2, out2
    assert "不构成投资建议" in out2, "未追加免责声明"


# ---------- 4. 多空辩论模块可导入/结构 ----------
def t_debate_module():
    from core.agents import graph
    assert hasattr(graph, "run_analysis") or hasattr(graph, "run"), "辩论图缺入口"
    from app.ui import debate_tab
    assert hasattr(debate_tab, "DebateTab"), "缺 DebateTab"


# ---------- 5. 回测引擎 ----------
def t_backtest():
    import numpy as np
    import pandas as pd
    from core.quant.backtest import run_backtest
    n = 200
    close = pd.Series(100 + np.cumsum(np.random.randn(n)),
                      index=pd.date_range("2025-01-01", periods=n))
    df = pd.DataFrame({"open": close, "high": close * 1.01,
                       "low": close * 0.99, "close": close, "volume": 1e6})
    res = run_backtest(df, "CN", "rsi_reversion")
    assert hasattr(res, "metrics"), "结果缺 metrics"
    for k in ("total_return_pct", "max_drawdown_pct", "sharpe", "win_rate_pct"):
        assert k in res.metrics, f"metrics 缺 {k}"


# ---------- 6. 产业图谱 ----------
def t_industry():
    from core.data import industry_graph as ig
    c = ig.get_concepts_by_stock("600519")
    assert isinstance(c, list), "get_concepts_by_stock 应返回 list"
    s = ig.get_stocks_by_concept("白酒")
    assert isinstance(s, list), "get_stocks_by_concept 应返回 list"


# ---------- 7. 本地 AI 检测 ----------
def t_local_ai():
    from core import llm_local
    v = llm_local.is_installed()
    assert isinstance(v, bool), "is_installed 应返回 bool"
    st = llm_local.local_ai_status()
    assert isinstance(st, dict), "local_ai_status 应返回 dict"


# ---------- 8. 配置管理 ----------
def t_config():
    from config_manager import get_deepseek_key
    key = get_deepseek_key()
    assert isinstance(key, str), "API key 应返回 str"


def t_env_file():
    assert os.path.exists(".env.example"), "缺 .env.example"
    txt = open(".env.example", encoding="utf-8").read()
    assert "DEEPSEEK_API_KEY" in txt, ".env.example 缺 DEEPSEEK_API_KEY"


if __name__ == "__main__":
    check("数据-日线", t_daily)
    check("数据-实时价", t_realtime)
    check("技术指标", t_indicators)
    check("合规过滤", t_compliance)
    check("多空辩论模块", t_debate_module)
    check("回测引擎", t_backtest)
    check("产业图谱", t_industry)
    check("本地AI检测", t_local_ai)
    check("配置API Key", t_config)
    check(".env.example", t_env_file)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n==== {passed}/{len(RESULTS)} 通过 ====")
    sys.exit(0 if passed == len(RESULTS) else 1)
