# -*- coding: utf-8 -*-
"""数据质量标签页（任务书A·模块二）：行情/财报数据质量评分 + 问题清单 + 来源标注。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QTextEdit, QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.dataquality")


def render_quality_card(q: dict) -> str:
    """把质量报告渲染为 HTML 卡片（暗色主题适配）。"""
    if not q.get("ok") and q.get("source") == "error":
        return (f"<span style='color:#FF1744'>取数失败：{'; '.join(q.get('issues', []))}</span>"
                f"<p style='color:#8B949E'>可检查网络或换一只股票重试。</p>")
    score = q.get("score", 0.0)
    passed = q.get("passed", False)
    color = "#00C853" if passed else "#FFA726"
    rows = q.get("rows", 0)
    source = q.get("source", "")
    fet = q.get("fetched_at") or ""
    checks = q.get("checks", {}) or {}
    issues = q.get("issues", [])
    lines = [
        "<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>",
        f"<h2>📊 数据质量报告</h2>",
        f"<p style='font-size:15px'>标的：<b>{q.get('ticker', '')}</b>　"
        f"评分：<b style='color:{color};font-size:20px'>{score}</b>/100　"
        f"状态：<b style='color:{color}'>{'✅ 合格' if passed else '⚠️ 需关注'}</b></p>",
        f"<p style='color:#8B949E'>样本 {rows} 行　数据源：{source or 'N/A'}　"
        f"获取时间：{fet or 'N/A'}</p>",
        "<hr>",
        "<h3>检查明细</h3><table style='border-collapse:collapse;width:100%'>",
    ]
    for k, v in checks.items():
        lines.append(
            f"<tr><td style='border:1px solid #1E2530;padding:6px;color:#8B949E'>{k}</td>"
            f"<td style='border:1px solid #1E2530;padding:6px'>{v}</td></tr>")
    lines.append("</table>")
    if issues:
        lines.append("<h3>发现的问题</h3><ul>")
        for it in issues:
            lines.append(f"<li style='color:#FFA726'>{it}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p style='color:#00C853'>✅ 未发现数据质量问题</p>")
    lines.append("</div>")
    return "".join(lines)


class DataQualityTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        top.addWidget(QLabel("代码："))
        self.input = QLineEdit()
        self.input.setPlaceholderText("如 600519 / AAPL / 000300")
        self.input.returnPressed.connect(self._run)
        top.addWidget(self.input, 1)
        self.btn = QPushButton("数据质量检测")
        self.btn.clicked.connect(self._run)
        top.addWidget(self.btn)
        lay.addLayout(top)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setText("输入股票代码，点击「数据质量检测」。\n"
                         "检测项：缺失值 / 非正价格 / 极端单日波动(>50%) / 交易日缺口。\n"
                         "结果自动写入本地质量报告库，分析报告中会标注数据来源与获取时间。")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.out)
        lay.addWidget(scroll, 1)

    def _run(self) -> None:
        code = self.input.text().strip().upper()
        if not code:
            return
        self.btn.setEnabled(False)
        self.out.setText("⏳ 正在取数并校验…")

        class _W(QThread):
            done = pyqtSignal(object)

            def run(self):
                try:
                    from core.data_quality import fetch_and_check
                    q = fetch_and_check(code)
                    self.done.emit(render_quality_card(q))
                except Exception as e:  # noqa: BLE001
                    self.done.emit(f"<span style='color:#FF1744'>检测失败：{e}</span>")

        w = _W()
        w.done.connect(lambda html: (self.out.setHtml(html), self.btn.setEnabled(True)))
        w.start()
