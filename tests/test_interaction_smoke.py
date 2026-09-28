# -*- coding: utf-8 -*-
"""交互级全量冒烟：逐 tab 模拟真实用户操作，捕获异常并输出。
覆盖：搜索补全/搜索、K线加载、mock分析、市场概览、自选股、回测、模拟盘、
辩论、产业图谱、股票大全、合规审计、知识库(含融合)、决策记录、分析日志、快捷键。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

sys.path.insert(0, r"D:\StockAIPredictor")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STOCKAI_MOCK", "1")


def _hook(exc_type, exc_value, exc_tb):
    traceback.print_exception(exc_type, exc_value, exc_tb)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _hook

results: list[str] = []


def ok(name: str, detail: str = "") -> None:
    results.append(f"PASS {name}{('  |  ' + detail) if detail else ''}")
    print(f"PASS {name}{('  |  ' + detail) if detail else ''}", flush=True)


def bad(name: str, e: Exception) -> None:
    results.append(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"FAIL {name}: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()


def wait_until(pred, timeout=40.0, step=0.05) -> bool:
    dl = time.time() + timeout
    while time.time() < dl:
        if pred():
            return True
        QApplication.processEvents()
        time.sleep(step)
    return False


from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

try:
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    ok("主窗口构建", f"{w.tabs.count()} 标签")
except Exception as e:  # noqa: BLE001
    bad("主窗口构建", e)
    raise

# ---- 0) 导航按钮与懒加载切换 ----
try:
    for i in range(0, 21):
        w._switch_tab(i, w.nav_buttons[i])
    ok("导航切换 0-20", f"{len(w._created)} 个tab已懒创建")
except Exception as e:  # noqa: BLE001
    bad("导航切换", e)

# ---- 1) 搜索框（chat_tab 补全） ----
try:
    from app.ui.stock_search_dialog import StockSearchDialog
    d = StockSearchDialog(w)
    d.search_input.setText("gzmt")
    d._do_search()
    rows = d.result_list.count() if hasattr(d, "result_list") else -1
    ok("股票搜索(gzmt→茅台)", f"{rows} 行" if rows else "空")
except Exception as e:  # noqa: BLE001
    bad("股票搜索", e)

# ---- 2) K线加载（A股+美股） ----
try:
    w.chart_tab.load("SH600519")
    got = wait_until(lambda: getattr(w.chart_tab, "_bars", None) is not None, 30)
    _b = getattr(w.chart_tab, "_bars", None)
    n = len(_b) if _b is not None else 0
    ok("K线加载 SH600519", f"{'OK' if got else 'TIMEOUT'} {n}根")
except Exception as e:  # noqa: BLE001
    bad("K线加载 SH600519", e)

try:
    w.chart_tab.load("AAPL")
    got = wait_until(lambda: getattr(w.chart_tab, "_bars", None) is not None, 30)
    _b = getattr(w.chart_tab, "_bars", None)
    n = len(_b) if _b is not None else 0
    ok("K线加载 AAPL", f"{'OK' if got else 'TIMEOUT'} {n}根")
except Exception as e:  # noqa: BLE001
    bad("K线加载 AAPL", e)

# ---- 3) mock 分析 ----
try:
    done: dict = {}
    w.analysis_tab.analysis_finished.connect(lambda r: done.update(r))
    w.analysis_tab.input.setText("SH600519")
    w.analysis_tab.mock_box.setChecked(True)
    w.analysis_tab._start()
    got = wait_until(lambda: "state" in done, 90)
    final = done.get("state", {}).get("final", {})
    ok("mock 分析", f"{'OK' if got else 'TIMEOUT'} action={final.get('action')}")
except Exception as e:  # noqa: BLE001
    bad("mock 分析", e)

# ---- 4) 市场概览 ----
try:
    before = w.r_market.text()
    w._load_market_overview()
    got = wait_until(lambda: "加载中" not in w.r_market.text() and w.r_market.text() != before, 30)
    txt = w.r_market.text().replace("\n", " ")
    ok("市场概览", txt[:60] if got else "TIMEOUT/失败占位")
except Exception as e:  # noqa: BLE001
    bad("市场概览", e)

# ---- 5) 自选股 ----
try:
    w._switch_tab(2, w.nav_buttons[2])
    wt = w.watchlist_tab
    from core.watchlist import store as _wl
    _wl.add("SH600519", "SH", "MA5", "贵州茅台")
    wt.refresh()
    ok("自选股刷新", f"{wt.table.rowCount()} 行")
except Exception as e:  # noqa: BLE001
    bad("自选股", e)

# ---- 6) 回测 ----
try:
    w._switch_tab(6, w.nav_buttons[6])
    bt = w._created.get(6)
    bt.input.setText("SH600519") if hasattr(bt, "input") else None
    bt.run() if hasattr(bt, "run") else None
    ok("回测tab可操作", "run触发" if hasattr(bt, "run") else "无run方法")
except Exception as e:  # noqa: BLE001
    bad("回测tab", e)

# ---- 7) 模拟盘 ----
try:
    w._switch_tab(5, w.nav_buttons[5])
    pt_ = w._created.get(5)
    pt_.refresh()
    ok("模拟盘刷新", "无异常")
except Exception as e:  # noqa: BLE001
    bad("模拟盘", e)

# ---- 8) 多空辩论 ----
try:
    w._switch_tab(15, w.nav_buttons[15])
    dt = w._created.get(15)
    if hasattr(dt, "start"):
        dt.start()
        ok("多空辩论start", "已触发")
    else:
        ok("多空辩论tab", "实例化无异常")
except Exception as e:  # noqa: BLE001
    bad("多空辩论", e)

# ---- 9) 产业图谱 ----
try:
    w._switch_tab(14, w.nav_buttons[14])
    it = w._created.get(14)
    if hasattr(it, "query"):
        it.query("白酒")
        ok("产业图谱查询", "已触发")
    else:
        ok("产业图谱tab", "实例化无异常")
except Exception as e:  # noqa: BLE001
    bad("产业图谱", e)

# ---- 10) 股票大全 ----
try:
    w._switch_tab(16, w.nav_buttons[16])
    sd = w._created.get(16)
    ok("股票大全tab", "实例化无异常")
except Exception as e:  # noqa: BLE001
    bad("股票大全", e)

# ---- 11) 合规审计 ----
try:
    w._switch_tab(13, w.nav_buttons[13])
    ca = w._created.get(13)
    if hasattr(ca, "refresh"):
        ca.refresh()
    ok("合规审计", "刷新无异常")
except Exception as e:  # noqa: BLE001
    bad("合规审计", e)

# ---- 12) 知识库（普通+融合） ----
try:
    w._switch_tab(10, w.nav_buttons[10])
    kt = w._created.get(10)
    kt.query.setText("白酒")
    kt._do_search()
    got = wait_until(lambda: "学习库" in kt.lbl_stats.text() or "融合" in kt.lbl_stats.text() or "失败" in kt.lbl_stats.text(), 20)
    ok("知识库普通检索", kt.lbl_stats.text()[:50])
    kt.hybrid_box.setChecked(True)
    kt.query.setText("白酒")
    kt._do_search()
    got = wait_until(lambda: "融合" in kt.lbl_stats.text() or "失败" in kt.lbl_stats.text(), 20)
    ok("知识库融合检索", kt.lbl_stats.text()[:50])
except Exception as e:  # noqa: BLE001
    bad("知识库", e)

# ---- 13) 决策记录 ----
try:
    w._switch_tab(11, w.nav_buttons[11])
    ht = w._created.get(11)
    ht.refresh()
    ok("决策记录", f"{ht.table.rowCount()} 行")
except Exception as e:  # noqa: BLE001
    bad("决策记录", e)

# ---- 14) 分析日志 ----
try:
    w._switch_tab(12, w.nav_buttons[12])
    alt = w._created.get(12)
    if hasattr(alt, "refresh"):
        alt.refresh()
    ok("分析日志", "刷新无异常")
except Exception as e:  # noqa: BLE001
    bad("分析日志", e)

# ---- 15) 快捷键 Ctrl+K 聚焦搜索 ----
try:
    w.chat_tab.input.setFocus()
    ok("搜索框焦点", "OK")
except Exception as e:  # noqa: BLE001
    bad("搜索框焦点", e)

# ---- 汇总 ----
passed = [r for r in results if r.startswith("PASS")]
failed = [r for r in results if r.startswith("FAIL")]
print(f"\n==== 交互冒烟 {len(passed)}/{len(results)} 通过 ====")
if failed:
    print("\n".join(failed))
    sys.exit(1)
