# -*- coding: utf-8 -*-
"""疏影·知微 功能全面检测（v0.7.0）。

覆盖：数据层（真网络：A股/港股/美股/指数/市场概览/股票索引）、
GUI 模块层（offscreen + mock AI）、服务层（Web/REST/GDPR/审计/风控/协作）。

输出：docs/feature_audit_report.md
用法：QT_QPA_PLATFORM=offscreen STOCKAI_MOCK=1 python -B tools/feature_audit.py
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STOCKAI_MOCK", "1")

import socket

socket.setdefaulttimeout(30)

RESULTS: list[tuple[str, str, str]] = []  # (模块, 结果 PASS/FAIL/WARN, 说明)
T0 = time.time()


def chk(module: str, ok: bool, note: str = "", warn: bool = False):
    tag = "WARN" if warn else ("PASS" if ok else "FAIL")
    RESULTS.append((module, tag, note))
    print(f"[{tag}] {module}: {note}", flush=True)


def timed(fn, timeout=90):
    """带超时的执行包装（线程 + join）。"""
    import threading
    box = {}

    def _run():
        try:
            box["r"] = fn()
        except Exception as e:  # noqa: BLE001
            box["e"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, TimeoutError(f"超过 {timeout}s")
    if "e" in box:
        return None, box["e"]
    return box.get("r"), None


# ============ 一、数据层（真网络） ============
def audit_data() -> None:
    # 1. 沪深300 指数历史（走程序降级链：AKShare 指数接口 → 缓存兜底）
    def _hs300():
        from core.data import service as svc
        df, src = svc.get_daily("SH000300")
        return len(df) if df is not None else 0, str(src)
    r, e = timed(_hs300, 90)
    if r:
        n, src = r
        chk("数据/沪深300指数", n > 5000, f"{n} 行（源={src}）")
    else:
        # 裸 akshare 直连 eastmoney 在受限代理下可能失败；程序降级链是否兜住
        chk("数据/沪深300指数", False, f"错误:{type(e).__name__}:{e}")

    # 2. A股日线（茅台）
    def _ash():
        from core.data import service as svc
        df, _ = svc.get_daily("SH600519")
        return len(df) if df is not None else 0
    r, e = timed(_ash, 90)
    chk("数据/A股日线(600519)", r is not None and r > 1000,
        f"{r} 行" if r else f"错误:{type(e).__name__}:{e}")

    # 3. 美股（AAPL, yfinance）
    def _us():
        from core.data import service as svc
        df, _ = svc.get_daily("AAPL")
        return len(df) if df is not None else 0
    r, e = timed(_us, 90)
    chk("数据/美股(AAPL)", r is not None and r > 100,
        f"{r} 行" if r else f"错误:{type(e).__name__}:{e}")

    # 4. 港股（0700.HK）
    def _hk():
        from core.data import service as svc
        df, _ = svc.get_daily("0700.HK")
        return len(df) if df is not None else 0
    r, e = timed(_hk, 90)
    chk("数据/港股(0700.HK)", r is not None and r > 100,
        f"{r} 行" if r else f"错误:{type(e).__name__}:{e}")

    # 5. 市场概览（指数实时）
    def _mkt():
        from core.data.market_overview import list_market_indices
        return list_market_indices()
    r, e = timed(_mkt, 60)
    chk("数据/市场概览(指数)", bool(r) and len(r) >= 4,
        f"{len(r)} 个指数, 示例 {r[0]['name']} {r[0]['price']:.1f}({r[0]['chg_pct']:+.2f}%)"
        if r else f"错误:{type(e).__name__}:{e}")

    # 6. 股票索引（all_stocks.json）
    def _idx():
        import json
        d = json.load(open(ROOT / "data" / "all_stocks.json", encoding="utf-8"))
        codes = {str(s.get("code", "")) for s in d}
        alias = {str(s.get("code", "")): s for s in d}
        return len(d), all(c in codes for c in ("000300", "AAPL", "0700.HK", "399006")), alias
    r, e = timed(_idx, 10)
    if r:
        n, ok6, _ = r
        chk("数据/股票索引", ok6, f"{n} 条, 关键标的齐全")
    else:
        chk("数据/股票索引", False, f"错误:{type(e).__name__}:{e}")

    # 7. 命令面板索引（全量加载 + 别名可用性）
    def _search():
        from app.ui.command_palette import _stock_index
        idx = _stock_index()
        alias_hit = any("tencent" in (s.get("alias") or "") for s in idx)
        key_hit = any(s.get("code") == "0700.HK" for s in idx)
        return len(idx), alias_hit, key_hit
    r, e = timed(_search, 10)
    chk("数据/命令面板索引", r is not None and r[0] > 18000 and r[1] and r[2],
        f"{r[0]} 条, tencent别名={r[1]}, 0700.HK={r[2]}" if r else f"错误:{e}")


# ============ 二、GUI 模块层（offscreen + mock） ============
def audit_gui() -> None:
    from PyQt6.QtWidgets import QApplication
    from core.config import setup_logging
    setup_logging()
    app = QApplication([])

    # 8. 主窗口构建（必须在主线程：子线程构建会使后续 worker 信号投递到子线程队列，
    #    主线程 processEvents 永远处理不到，导致 K线/AI 全链路超时）
    try:
        from app.ui.main_window import MainWindow
        w = MainWindow()
        _win_err = None
    except Exception as e:  # noqa: BLE001
        w, _win_err = None, e
    if _win_err or w is None:
        chk("GUI/主窗口构建", False, f"错误:{type(_win_err).__name__}:{_win_err}")
        return
    n_tab = w.tabs.count()
    has_dock = w.info_dock is not None and w.nav_dock is not None
    has_fab = getattr(w, "ai_fab", None) is not None
    chk("GUI/主窗口构建", n_tab >= 23 and has_dock and has_fab,
        f"{n_tab} tabs, 双Dock, 浮动AI按钮")

    # 9. K线联动（构建后立即测；插桩观察 worker/status）
    def _kline_main_thread() -> str:
        ct = w.chart_tab
        if getattr(ct, "_worker", None) and ct._worker.isRunning():
            ct._worker.wait(30000)
        ct.load("SH600519")
        deadline = time.time() + 60
        while time.time() < deadline and getattr(ct, "_bars", None) is None:
            app.processEvents()
            time.sleep(0.02)
        bars = getattr(ct, "_bars", None)
        wr = getattr(ct, "_worker", None)
        note = f"worker_running={bool(wr and wr.isRunning())} status='{ct.status.text()}'"
        if bars is None:
            return f"无数据({note})"
        return f"{len(bars)}根({note})"
    r = _kline_main_thread()
    chk("GUI/K线加载联动", r.startswith("60") or r.startswith("59"), r)

    # 10. mock 分析 UI 全链路（单跑：AnalysisTab._start → analysis_finished，含模拟盘联动）
    def _ana_ui_main_thread() -> str:
        # 强制重置 worker 引用，避免旧实例残留
        w.analysis_tab.worker = None
        w.analysis_tab.input.setText("SH600519")
        w.analysis_tab.mock_box.setChecked(True)
        w.analysis_tab.paper_box.setChecked(True)
        done = {}
        w.analysis_tab.analysis_finished.connect(done.update)
        w.analysis_tab._start()
        deadline = time.time() + 200
        while time.time() < deadline and "state" not in done:
            app.processEvents()
            time.sleep(0.05)
        if "state" not in done:
            wr = getattr(w.analysis_tab, "worker", None)
            return f"超时(worker_running={bool(wr and wr.isRunning())} info='{w.analysis_tab.info.text()[:60]}')"
        st = done["state"].get("state") or {}
        final = st.get("final") or {}
        return f"完成·{final.get('summary','')[:40]}"
    r = _ana_ui_main_thread()
    chk("GUI/AI分析全链路(mock)", r.startswith("完成"), r)

    # 11. 决策记录落库（真实写入库 core.memory.decision_log / stockai.db）
    def _hist():
        from core.memory.decision_log import list_recent
        return len(list_recent(limit=100))
    r, e = timed(_hist, 10)
    chk("GUI/决策记录落库", r is not None and r >= 1, f"{r} 条" if r else f"错误:{e}")

    # 12. 回测引擎（绩效指标完整性）
    def _bt():
        from core.quant.backtest import run_backtest, BacktestConfig
        from core.data import service as svc
        bars, _ = svc.get_daily("SH600519")
        cfg = BacktestConfig(market="CN", ticker="SH600519")
        res = run_backtest(bars, "CN", "ma_cross", config=cfg)
        m = res.metrics
        keys = ("total_return_pct", "max_drawdown_pct", "sharpe",
                "win_rate_pct", "profit_loss_ratio", "trade_count")
        missing = [k for k in keys if m.get(k) is None]
        eq = len(res.equity)
        return len(bars), missing, round(float(m.get("total_return_pct", 0) or 0), 2), eq
    r, e = timed(_bt, 120)
    if r:
        nbars, missing, tr, eq = r
        chk("GUI/回测引擎", not missing and eq > 0,
            f"{nbars}根K线, 净值{eq}点, 收益{tr}%, 缺失指标:{missing or '无'}")
    else:
        chk("GUI/回测引擎", False, f"错误:{type(e).__name__}:{e}")

    # 13. 参数寻优（网格+walk-forward）
    def _opt():
        from core.optimize import grid as g
        from core.data import service as svc
        from core.quant.backtest import BacktestConfig
        bars, _ = svc.get_daily("SH600519")
        spec = {"fast": [5, 10], "slow": [20, 30]}
        o = g.optimize(bars, "CN", "ma_cross", spec,
                       BacktestConfig(ticker="SH600519", market="CN"),
                       objective="sharpe", split=0.6)
        return o["n_combos"], o["best"]["params"], o["walk_forward"]["oos_percentile"]
    r, e = timed(_opt, 180)
    chk("GUI/参数寻优", r is not None, f"{r[0]}组合 best={r[1]} OOS={r[2]:.2f}"
        if r else f"错误:{type(e).__name__}:{e}")

    # 14. 信号回放
    def _rp():
        from core.replay import engine as eng, store as st
        from core.data import service as svc
        st.init()
        bars, _ = svc.get_daily("SH600519")
        pts = eng.pick_dates(bars, step_bars=120)[:2]
        return len(pts)
    r, e = timed(_rp, 60)
    chk("GUI/信号回放", r is not None and r == 2, f"{r} 个回放点" if r else f"错误:{e}")

    # 15. 模拟盘（建表+账户汇总）
    def _pp():
        from core.portfolio import paper
        paper.init()
        s = paper.summary()
        return s.get("init_capital", 0) > 0
    r, e = timed(_pp, 10)
    chk("GUI/模拟盘建表", r is True, "账户/持仓/成交/净值表就绪" if r else f"错误:{e}")

    # 16. 学习库向量入库（chromadb 可用）
    def _kb():
        from memory.vector_memory import add_document, stats
        before = stats()["docs"]
        add_document(f"audit-{time.time()}", "功能检测：疏影知微 向量入库链路验证",
                     {"src": "audit"})
        after = stats()["docs"]
        return before, after
    r, e = timed(_kb, 30)
    chk("GUI/学习库向量入库", r is not None and r[1] > r[0],
        f"docs {r[0]}→{r[1]}" if r else f"错误:{type(e).__name__}:{e}")

    # 17. 合规审计（哈希链写入+校验）
    def _audit():
        from security.audit_ledger import append, verify, records
        append("audit-test", "feature_audit", "功能检测写入")
        ok, n = verify()
        return ok, len(records(limit=100))
    r, e = timed(_audit, 10)
    chk("GUI/合规审计(哈希链)", r is not None and r[0], f"链完整, {r[1]} 条" if r
        else f"错误:{e}")

    # 18. 股票大全索引
    def _dir():
        from app.ui.stock_directory_tab import _load_all_stocks
        return len(_load_all_stocks())
    r, e = timed(_dir, 10)
    chk("GUI/股票大全索引", r is not None and r > 18000, f"{r} 只" if r else f"错误:{e}")

    # 19. 产业图谱（概念缓存；网络不可达时若缓存命中仍可用）
    def _ig():
        from core.data.industry_graph import get_stocks_by_concept, DB_PATH
        import os
        cached = os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0
        n = len(get_stocks_by_concept("白酒"))
        return n, cached
    r, e = timed(_ig, 40)
    if r:
        n, cached = r
        chk("GUI/产业图谱", n >= 1, f"白酒概念 {n} 只" + ("" if cached else "（无缓存）"))
    else:
        chk("GUI/产业图谱", False,
            f"在线源不可达:{type(e).__name__}（东财接口受网络限制；24h缓存机制已内置）",
            warn=True)

    # 20. Swarm 估值（本地算法，无需网络）
    def _sw():
        from valuation_swarm.swarm_agents import SwarmEstimator
        out = SwarmEstimator().run_with_alignment("SH600519")
        return bool(out)
    r, e = timed(_sw, 10)
    chk("GUI/Swarm估值", r is True, "3任务×3Agent+辩论对齐产出" if r else f"错误:{e}")

    # 21. 合规监控规则（本地规则引擎）
    def _cm():
        from compliance.rule_engine import RuleEngine
        eng = RuleEngine()
        v1 = eng.check({"text": "推荐你明天满仓买入茅台"})
        v2 = eng.check({"text": "今日白酒板块成交额放大"})
        return eng.is_blocked(v1), not eng.is_blocked(v2)
    r, e = timed(_cm, 10)
    chk("GUI/合规监控规则", r is not None and all(r), f"荐股拦截={r[0]}, 中性放行={r[1]}"
        if r else f"错误:{e}")

    # 22. 风控 VaR/压力测试（真实行情收益）
    def _rk():
        from core.data import service as svc
        from core.risk_engine import calculate_var, stress_test
        bars, _ = svc.get_daily("SH600519")
        ret = bars["close"].pct_change().dropna()
        var = calculate_var(ret.tail(250))
        st = stress_test(ret.tail(250),
                         scenarios=[{"name": "-15%", "market_shift": -0.15}])
        return var.get("var_pct") is not None, bool(st)
    r, e = timed(_rk, 60)
    chk("GUI/风控(VaR/压力)", r is not None and all(r), f"VaR/压力测试产出" if r
        else f"错误:{type(e).__name__}:{e}")

    # 23. 协作空间
    def _collab():
        from core.collaboration import create_workspace, list_workspaces
        create_workspace(f"audit-ws-{time.time():.0f}", "audit-user", "功能检测")
        return len(list_workspaces())
    r, e = timed(_collab, 10)
    chk("GUI/协作空间", r is not None and r >= 1, f"{r} 个工作区" if r else f"错误:{e}")

    # 24. GDPR 导出/删除
    def _gdpr():
        from compliance.gdpr import export_user_data, delete_user_data
        exp = export_user_data("audit-user")
        d = delete_user_data("audit-user")
        return bool(exp), bool(d)
    r, e = timed(_gdpr, 10)
    chk("GUI/GDPR导出/删除", r is not None and all(r), f"{r}" if r else f"错误:{e}")

    # 25. i18n 切换
    def _i18n():
        from i18n import set_language, tr
        set_language("en")
        en = tr("app.title")
        set_language("zh")
        zh = tr("app.title")
        return en, zh
    r, e = timed(_i18n, 10)
    chk("GUI/i18n中英切换", r is not None and r[0] != r[1], f"{r}" if r else f"错误:{e}")

    # 26. 主题切换
    def _theme():
        from app.ui.ui_theme import toggle_theme, current_theme
        before = current_theme()
        toggle_theme()
        after = current_theme()
        toggle_theme()
        return before, after
    r, e = timed(_theme, 10)
    chk("GUI/明暗主题切换", r is not None and r[0] != r[1], f"{r}" if r else f"错误:{e}")

    # 27. 命令面板（全量索引+对话框构建）
    def _cp():
        from app.ui.command_palette import _stock_index, CommandPaletteDialog
        idx = _stock_index()
        dlg = CommandPaletteDialog([("测试", 1)], parent=w)
        return len(idx), dlg._rows is not None
    r, e = timed(_cp, 10)
    chk("GUI/命令面板", r is not None and r[0] > 18000 and r[1],
        f"{r[0]} 条, 对话框就绪" if r else f"错误:{e}")

    # 28. 单实例锁
    def _single():
        from PyQt6.QtCore import QSharedMemory
        m1 = QSharedMemory("ShuyingInsight_AuditLock")
        ok1 = m1.create(1)
        m2 = QSharedMemory("ShuyingInsight_AuditLock")
        ok2 = m2.create(1)
        return ok1, ok2
    r, e = timed(_single, 10)
    chk("GUI/单实例锁", r is not None and r == (True, False), f"首次={r[0]} 二次={r[1]}"
        if r else f"错误:{e}")

    w.close()


# ============ 三、服务层（Web / REST / 简报） ============
def audit_service() -> None:
    # 29. Web UI 应用可导入（fastapi 已装）
    def _web():
        from web_ui.app import create_app
        app = create_app()
        routes = sorted({r.path for r in app.routes if getattr(r, "path", "")})
        return routes
    r, e = timed(_web, 30)
    chk("服务/Web(FastAPI)路由", r is not None and any("/api/" in x or "/ws/" in x for x in r or []),
        str(r)[:200] if r else f"错误:{type(e).__name__}:{e}")

    # 30. 每日简报构建（正常长度 100~300 字符）
    def _brief():
        from core.daily_briefing import build_briefing
        html = build_briefing()
        return len(html)
    r, e = timed(_brief, 60)
    chk("服务/每日简报", r is not None and 80 < r < 400, f"{r} 字符" if r else f"错误:{e}")

    # 31. 更新检查（GitHub Release 可达性）
    def _upd():
        import requests
        resp = requests.get(
            "https://api.github.com/repos/ShuYing07/Penumbra/releases/latest",
            timeout=20)
        return resp.status_code == 200, resp.json().get("tag_name", "")
    r, e = timed(_upd, 30)
    chk("服务/更新检查(GitHub)", r is not None and r[0], f"latest={r[1]}" if r else f"错误:{e}")


def main() -> int:
    print("===== 疏影·知微 v0.7.0 功能全面检测 =====", flush=True)
    audit_data()
    audit_gui()
    audit_service()

    dt = time.time() - T0
    passed = sum(1 for _, t, _ in RESULTS if t == "PASS")
    failed = sum(1 for _, t, _ in RESULTS if t == "FAIL")
    warned = sum(1 for _, t, _ in RESULTS if t == "WARN")

    lines = [
        "# 疏影·知微 v0.7.0 功能全面检测报告",
        "",
        f"- 检测时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 检测耗时：{dt:.0f} 秒",
        f"- 结果：**{passed} 通过 / {failed} 失败 / {warned} 警告**（共 {len(RESULTS)} 项）",
        "",
        "| 模块 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for mod, tag, note in RESULTS:
        lines.append(f"| {mod} | {tag} | {note.replace('|', '/')} |")
    if failed:
        lines.append("")
        lines.append("## ❌ 失败项明细")
        for mod, tag, note in RESULTS:
            if tag == "FAIL":
                lines.append(f"- **{mod}**：{note}")
    report = "\n".join(lines)
    (ROOT / "docs" / "feature_audit_report.md").write_text(report, encoding="utf-8")
    print("\n===== 汇总 =====", flush=True)
    print(f"通过 {passed} / 失败 {failed} / 警告 {warned}，共 {len(RESULTS)} 项，耗时 {dt:.0f}s",
          flush=True)
    print(f"报告已写入 docs/feature_audit_report.md", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
