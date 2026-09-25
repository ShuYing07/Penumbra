# -*- coding: utf-8 -*-
"""GUI 冒烟：offscreen 模式实例化主窗口 → mock 跑完整分析 → 验证信号/报告/图表/历史联动。

运行：venv\\Scripts\\python.exe scripts\\smoke_gui.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # 无显示环境冒烟

from PyQt6.QtWidgets import QApplication  # noqa: E402


def wait_until(pred, timeout_s: float, app) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    from app.ui.main_window import MainWindow

    app = QApplication([])
    win = MainWindow()
    win.show()
    print("PASS 窗口构建（3 标签 + 状态栏）")

    # ---- 1. mock 全链路（SH600519 行情已缓存，不依赖余额）----
    done = {}
    win.analysis_tab.analysis_finished.connect(lambda r: done.update(r))
    win.analysis_tab.input.setText("SH600519")
    win.analysis_tab.mock_box.setChecked(True)
    win.analysis_tab._start()
    ok = wait_until(lambda: "state" in done, 180, app)
    assert ok, "mock 分析超时未完成"
    state = done["state"]
    final = state["final"]
    assert final.get("action"), "final 缺少 action"
    report_text = win.analysis_tab.report.toPlainText()
    assert "最终结论" in report_text and "免责声明" in report_text, "报告未渲染"
    marks = [win.analysis_tab.progress.item(i).text().split()[0] for i in range(8)]
    assert all(m in ("✅", "⚠️") for m in marks), f"8 节点进度异常: {marks}"
    print(f"PASS mock 全链路：{final['action']} 仓位{final['position_pct']}% "
          f"报告{len(report_text)}字 8节点[{','.join(marks)}] 决策#{done['decision_id']}")

    # ---- 2. K线图页自动联动加载 ----
    ok = wait_until(lambda: win.chart_tab._bars is not None and len(win.chart_tab.price.items()) > 0,
                    120, app)
    assert ok, "K线图未联动加载"
    assert "最新收盘" in win.chart_tab.status.text(), f"图表状态异常: {win.chart_tab.status.text()}"
    print(f"PASS K线联动：{win.chart_tab.status.text()}")

    # ---- 3. 决策记录联动刷新 ----
    assert win.history_tab.table.rowCount() >= 1, "决策记录为空"
    print(f"PASS 决策记录：{win.history_tab.table.rowCount()} 条")

    print("\nGUI 冒烟全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
