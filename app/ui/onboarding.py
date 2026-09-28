# -*- coding: utf-8 -*-
"""首次启动欢迎引导（3 页，可跳过）。

参考 Vibe-Research / Stonks 的开箱即用体验：
- 第 1 页：输入代码 → 查看 K 线；
- 第 2 页：运行 AI 分析 → 多空辩论；
- 第 3 页：本地优先 · 数据主权。
首次启动（QSettings first_run 标志）自动弹出，之后不再打扰。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                             QStackedWidget, QVBoxLayout, QWidget)


_PAGES = [
    ("🚀 欢迎使用 疏影·知微", [
        "本地优先的开源 AI 金融研究终端。",
        "数据不出本地：自选股、分析历史、持仓只存在于你自己的电脑。",
        "无需注册，无账号体系，无云端收集。",
    ]),
    ("🔍 第一步：输入代码看数据", [
        "在搜索框输入 600519 / AAPL / 0700.HK（也支持中文名、拼音）。",
        "回车后自动加载 K 线、技术指标与 AI 摘要。",
        "示例：输入「茅台」或「gzmt」即可找到贵州茅台。",
    ]),
    ("⚔️ 第二步：深入研究", [
        "点击「分析」运行技术面/基本面/新闻面多维报告；",
        "「多空辩论」让不同模型分饰多空、逐点对抗；",
        "「回测」「参数寻优」验证你的策略假设。",
        "所有 AI 输出均强制附加免责声明，仅作数据展示。",
    ]),
]


class OnboardingDialog(QDialog):
    """3 页欢迎引导（可跳过）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("欢迎使用 疏影·知微")
        self.resize(560, 360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)

        self.stack = QStackedWidget()
        for title, lines in _PAGES:
            page = QVBoxLayout()
            t = QLabel(title)
            t.setStyleSheet("font-size:20px; font-weight:bold;")
            page.addWidget(t)
            for ln in lines:
                l = QLabel("· " + ln)
                l.setWordWrap(True)
                l.setStyleSheet("color:#8B949E; font-size:13px;")
                page.addWidget(l)
            page.addStretch(1)
            w = QWidget()
            w.setLayout(page)
            self.stack.addWidget(w)
        lay.addWidget(self.stack, 1)

        row = QHBoxLayout()
        self.skip_btn = QPushButton("跳过引导")
        self.skip_btn.clicked.connect(self.reject)
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        self.prev_btn = QPushButton("上一步")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._prev)
        self.next_btn = QPushButton("下一步 →")
        self.next_btn.clicked.connect(self._next)
        row.addWidget(self.prev_btn)
        row.addWidget(self.next_btn)
        lay.addLayout(row)

        self._idx = 0
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.setEnabled(self._idx > 0)
        self.next_btn.setText("开始使用 🎉" if self._idx == len(_PAGES) - 1 else "下一步 →")

    def _prev(self) -> None:
        if self._idx > 0:
            self._idx -= 1
            self.stack.setCurrentIndex(self._idx)
            self._update_buttons()

    def _next(self) -> None:
        if self._idx < len(_PAGES) - 1:
            self._idx += 1
            self.stack.setCurrentIndex(self._idx)
            self._update_buttons()
        else:
            self.accept()
