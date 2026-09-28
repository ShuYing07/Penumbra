# -*- coding: utf-8 -*-
"""合规监控标签页：持续合规监控 + 规则引擎 + 人工审核队列。

实时监测 AI 输出是否触发合规红线；block 级拦截、warn 级转人工。
"""
from __future__ import annotations

import logging

from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QTextEdit, QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.compliance_monitor")


class ComplianceMonitorTab(QWidget):
    """合规监控面板（规则引擎 + 持续监控 Agent）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            from compliance.continuous_monitor import ContinuousMonitor
            self.monitor = ContinuousMonitor()
        except Exception as e:  # noqa: BLE001
            log.warning("合规监控初始化失败: %s", e)
            self.monitor = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)

        tip = QLabel(
            "持续合规监控：实时检测禁用词 / 投资限制 / 风险阈值；"
            "block 级输出被拦截，warn 级进入下方人工审核队列。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8B949E; font-size:12px;")
        lay.addWidget(tip)

        row = QHBoxLayout()
        row.addWidget(QLabel("监测文本："))
        self.input = QTextEdit()
        self.input.setPlaceholderText(
            "粘贴一段待监测的 AI 输出，例如：\n"
            "「该股短期必涨，稳赚不赔，建议满仓跟进」")
        self.input.setMaximumHeight(80)
        row.addWidget(self.input, 1)
        self.check_btn = QPushButton("🔎 监测")
        self.check_btn.setStyleSheet(
            "background-color:#00E5FF; color:#0A0E17; border-radius:8px; padding:6px 14px;")
        self.check_btn.clicked.connect(self._check)
        row.addWidget(self.check_btn)
        lay.addLayout(row)

        self.result = QLabel("（尚未监测）")
        self.result.setWordWrap(True)
        self.result.setStyleSheet(
            "background-color:#131722; border:1px solid #1E2530; border-radius:12px;"
            "color:#E6EDF3; padding:8px;")
        lay.addWidget(self.result)

        lay.addWidget(QLabel("人工审核队列（open 项）"))
        self.review_list = QListWidget()
        self.review_list.setStyleSheet(
            "background-color:#131722; border:1px solid #1E2530; border-radius:8px;"
            "color:#E6EDF3;")
        lay.addWidget(self.review_list, 1)

        brow = QHBoxLayout()
        self.approve_btn = QPushButton("✅ 通过选中项")
        self.approve_btn.clicked.connect(lambda: self._review(True))
        self.close_btn = QPushButton("❌ 关闭选中项")
        self.close_btn.clicked.connect(lambda: self._review(False))
        self.refresh_btn = QPushButton("↻ 刷新队列")
        self.refresh_btn.clicked.connect(self._refresh)
        brow.addWidget(self.approve_btn)
        brow.addWidget(self.close_btn)
        brow.addWidget(self.refresh_btn)
        brow.addStretch(1)
        lay.addLayout(brow)

        self._refresh()

    def _check(self) -> None:
        if self.monitor is None:
            self.result.setText("合规监控引擎不可用（依赖 compliance 模块）")
            return
        text = self.input.toPlainText().strip()
        if not text:
            self.result.setText("请输入待监测文本。")
            return
        r = self.monitor.monitor(text, ticker="manual")
        lines = [
            f"检查次数：{r['checked']} | 本次拦截：{r['blocked']} | "
            f"本次警告：{r['warned']} | 累计拦截：{r['blocked_total']}",
            "",
            f"输出状态：{'⚠️ 已拦截（内容不展示）' if r['blocked'] else '✅ 通过'}",
            "",
            "命中明细：",
        ]
        for v in r["violations"]:
            lines.append(f"- [{v['level']}] {v.get('detail', '')} "
                         f"({v.get('rule', '')})")
        if not r["violations"]:
            lines.append("（无违规项）")
        self.result.setText("\n".join(lines))
        self._refresh()

    def _refresh(self) -> None:
        self.review_list.clear()
        if self.monitor is None:
            return
        for item in self.monitor.pending_reviews():
            self.review_list.addItem(
                QListWidgetItem(f"#{item['id']} [{item['level']}] {item['detail']} "
                                f"({item['ticker']})"))
        if self.review_list.count() == 0:
            self.review_list.addItem(QListWidgetItem("（队列为空）"))

    def _review(self, approve: bool) -> None:
        if self.monitor is None:
            return
        cur = self.review_list.currentRow()
        items = self.monitor.pending_reviews()
        if cur < 0 or cur >= len(items):
            return
        self.monitor.review(items[cur]["id"], approve=approve, note="UI 人工复核")
        self._refresh()
