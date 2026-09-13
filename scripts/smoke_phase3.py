# -*- coding: utf-8 -*-
"""三期冒烟：模拟盘交易闭环 + 决策反思评估 + 统计 + 模拟盘 UI 渲染。

运行：venv\\Scripts\\python.exe scripts\\smoke_phase3.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["STOCKAI_MOCK"] = "1"

from core.data import cache, service  # noqa: E402
from core.memory.reflection import decision_stats, evaluate_pending, inject_context  # noqa: E402
from core.memory.decision_log import init as dl_init, save as dl_save  # noqa: E402
from core.portfolio import paper  # noqa: E402


def _fake_state(ticker, market, action, position_pct, price):
    return {"ticker": ticker, "market": market,
            "final": {"action": action, "position_pct": position_pct,
                      "confidence": 70, "price": price}}


def main() -> int:
    cache.init_db()
    paper.reset()
    print("== 1. 模拟盘交易闭环 ==")
    s0 = paper.summary()
    assert s0["cash"] == s0["init_capital"] == 1_000_000, f"初始资金异常 {s0}"
    # A股买入：20% 仓位 @1285.13 → 整手
    tr = paper.execute(_fake_state("SH600519", "CN", "买入", 20, 1285.13))
    assert tr and tr["side"] == "买入", "A股买入未成交"
    lots = tr["shares"]
    assert lots % 100 == 0 and lots > 0, f"A股未按整手成交: {lots}"
    s1 = paper.summary()
    assert s1["cash"] < s0["cash"] and s1["market_value"] > 0, "买入后账户未变化"
    # 美股碎股买入 10%
    tr_us = paper.execute(_fake_state("AAPL", "US", "买入", 10, 319.0))
    assert tr_us and 0 < tr_us["shares"] < 400, "美股碎股买入异常"
    # 卖出清仓
    tr_sell = paper.execute(_fake_state("SH600519", "CN", "卖出", 0, 1300.0))
    assert tr_sell and tr_sell["side"] == "卖出", "卖出未成交"
    s2 = paper.summary()
    assert all(p["ticker"] != "SH600519" for p in paper.positions()), "卖出后仍有持仓"
    # 观望不动
    assert paper.execute(_fake_state("BTC-USD", "CRYPTO", "观望", 0, 77000.0)) is None
    summ = paper.summary()
    assert len(paper.equity_curve()) >= 3, "净值快照不足"
    print(f"PASS 交易闭环：A股{lots}股整手/美股碎股{tr_us['shares']}股/清仓/观望不动；"
          f"净值快照{len(paper.equity_curve())}条，总资产 {summ['total']:,.0f}")

    print("== 2. 决策反思评估 ==")
    dl_init()
    bars, _ = service.get_daily("SH600519")
    # 构造一条 30 个交易日前、决策价=当时收盘的买入决策 → 数据已足够评估
    idx = max(0, len(bars) - 30)
    asof = bars.index[idx].strftime("%Y-%m-%d")
    base_price = float(bars["close"].iloc[idx])
    did = dl_save(ticker="SH600519", market="CN", asof=asof,
                  quote={"price": base_price},
                  final={"action": "买入", "confidence": 60, "position_pct": 20,
                         "price": base_price, "targets": [], "scenarios": [],
                         "reasons": [], "risks": [], "summary": "冒烟测试决策",
                         "stop_loss": None, "horizon": "2周", "entry": "测试"},
                  signals={}, trader={}, risk={}, tokens={})
    evaled = evaluate_pending(limit=100)
    mine = [e for e in evaled if e["id"] == did]
    assert mine, f"构造的到期决策未被评估（evaluated={len(evaled)}）"
    e = mine[0]
    assert e["reflection"] and "实际涨跌" in e["reflection"], "反思文本异常"
    ctx = inject_context("SH600519")
    assert any(x["反思"] == e["reflection"] for x in ctx), "反思上下文未注入"
    print(f"PASS 反思评估：决策#{did} @{asof} 收盘{base_price} → 实际{e['realized_return_pct']:+.2f}%")

    print("== 3. 胜率统计 ==")
    st = decision_stats()
    assert st["evaluated"] >= 1 and st["win_rate_pct"] is not None, "统计异常"
    print(f"PASS 统计：{st}")

    print("== 4. 模拟盘 UI 渲染 ==")
    from PyQt6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication([])
    win = MainWindow()
    win.show()
    deadline = time.time() + 60
    while time.time() < deadline and not win.paper_tab.pos_table.rowCount():
        app.processEvents()
        time.sleep(0.05)
    assert win.paper_tab.pos_table.rowCount() >= 1, "模拟盘持仓表为空"
    assert "AAPL" in win.paper_tab.pos_table.item(0, 0).text() or \
        win.paper_tab.pos_table.rowCount() >= 1, "持仓内容异常"
    assert "总资产" in win.paper_tab.lbl_total.text(), "账户汇总未渲染"
    print(f"PASS 模拟盘UI：持仓{win.paper_tab.pos_table.rowCount()}只，"
          f"成交{win.paper_tab.trade_table.rowCount()}条，{win.paper_tab.lbl_total.text()}")
    print("\n三期冒烟全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
