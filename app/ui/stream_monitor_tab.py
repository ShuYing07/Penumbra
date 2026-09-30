# -*- coding: utf-8 -*-
"""实时流状态面板（模块二）：Kafka/内存总线 topic 速率、延迟、积压、去重统计。

- 后端自动识别：Kafka（已装 confluent-kafka 且 broker 可达）或内存总线（默认）。
- 提供"注入演示消息"按钮：向 news.raw / market.tick / filings.new 发送样例，
  验证 去重→情感→聚合→SQLite 全链路。
"""
from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QTextEdit, QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.stream")

from streaming.stream_engine import (ALL_TOPICS, StreamEngine, StreamProcessor,
                                     TOPIC_MARKET_TICK, TOPIC_NEWS_RAW,
                                     TOPIC_FILINGS_NEW)


def _render(stats: dict) -> str:
    lines = ["<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>",
             "<h2>⚡ 实时流状态</h2>"]
    proc = stats.pop("_processor", {}) or {}
    backend = "memory"
    lines.append(f"<p>后端：<b style='color:#00B4D8'>{backend}</b>　"
                 f"已处理 <b>{proc.get('processed', 0)}</b> 条　"
                 f"去重跳过 <b>{proc.get('duplicates_skipped', 0)}</b> 条</p>")
    lines.append("<table style='border-collapse:collapse;width:100%'>")
    lines.append("<tr><th style='border:1px solid #1E2530;padding:6px;color:#8B949E'>Topic</th>"
                 "<th style='border:1px solid #1E2530;padding:6px;color:#8B949E'>消息数</th>"
                 "<th style='border:1px solid #1E2530;padding:6px;color:#8B949E'>速率/分</th>"
                 "<th style='border:1px solid #1E2530;padding:6px;color:#8B949E'>积压</th>"
                 "<th style='border:1px solid #1E2530;padding:6px;color:#8B949E'>丢弃</th>"
                 "<th style='border:1px solid #1E2530;padding:6px;color:#8B949E'>最后消息</th></tr>")
    for t in ALL_TOPICS:
        s = stats.get(t, {})
        last = s.get("last_ts")
        last_s = time.strftime("%H:%M:%S", time.localtime(last)) if last else "—"
        lines.append(
            f"<tr><td style='border:1px solid #1E2530;padding:6px'>{t}</td>"
            f"<td style='border:1px solid #1E2530;padding:6px'>{s.get('published', 0)}</td>"
            f"<td style='border:1px solid #1E2530;padding:6px'>{s.get('rate_per_min', 0)}</td>"
            f"<td style='border:1px solid #1E2530;padding:6px'>{s.get('pending', 0)}</td>"
            f"<td style='border:1px solid #1E2530;padding:6px'>{s.get('dropped', 0)}</td>"
            f"<td style='border:1px solid #1E2530;padding:6px'>{last_s}</td></tr>")
    lines.append("</table>")
    lines.append("<p style='color:#8B949E'>窗口聚合：最近 5 分钟成交量均值（滑窗，过期自动剔除）</p>")
    lines.append("</div>")
    return "".join(lines)


class StreamMonitorTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.btn_start = QPushButton("启动处理")
        self.btn_start.clicked.connect(self._start)
        top.addWidget(self.btn_start)
        self.btn_stop = QPushButton("停止处理")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_stop.setEnabled(False)
        top.addWidget(self.btn_stop)
        self.btn_demo = QPushButton("注入演示消息")
        self.btn_demo.clicked.connect(self._demo)
        top.addWidget(self.btn_demo)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#8B949E")
        top.addWidget(self.status, 1)
        lay.addLayout(top)

        hint = QLabel("后端自动选择：安装 confluent-kafka 且 broker 可达 → 真实 Kafka；否则内存总线。\n"
                      "演示消息会走完：news.raw→情感分析→news.processed；market.tick→窗口聚合→SQLite；"
                      "filings.new→公告解析。")
        hint.setStyleSheet("color:#6B7488")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setText("点击「启动处理」后，可注入演示消息观察全链路统计。")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.out)
        lay.addWidget(scroll, 1)

        self._engine: StreamEngine | None = None
        self._proc: StreamProcessor | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _start(self):
        if self._proc is None:
            self._engine = StreamEngine(mode="auto")
            self._proc = StreamProcessor(self._engine, window_seconds=300)
            self._proc.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status.setText(f"运行中 · 后端={self._engine.backend_name()}")
        self._refresh()

    def _stop(self):
        if self._proc:
            self._proc.stop()
            self._proc = None
            self._engine = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status.setText("已停止")
        self._refresh()

    def _demo(self):
        if self._proc is None:
            self._start()
        if self._engine is None:
            return
        eng = self._engine
        eng.publish(TOPIC_NEWS_RAW, "demo-news-1",
                    {"title": "某公司净利润增长超预期，回购股份，机构看好"})
        eng.publish(TOPIC_NEWS_RAW, "demo-news-1",
                    {"title": "某公司净利润增长超预期，回购股份，机构看好"})  # 重复
        eng.publish(TOPIC_MARKET_TICK, "600519", {"price": 1700.0, "volume": 1200})
        eng.publish(TOPIC_MARKET_TICK, "600519", {"price": 1705.0, "volume": 1800})
        eng.publish(TOPIC_MARKET_TICK, "300750", {"price": 250.0, "volume": 900})
        eng.publish(TOPIC_FILINGS_NEW, "demo-filing-1",
                    {"title": "关于签订重大合同的公告", "code": "600519"})
        self.status.setText("已注入 6 条演示消息（含 1 条重复，用于验证去重）")

    def _refresh(self):
        if self._proc is None:
            return
        try:
            stats = self._proc.stats()
        except Exception as e:  # noqa: BLE001
            self.out.setHtml(f"<p style='color:#FF1744'>统计失败：{str(e)[:100]}</p>")
            return
        self.out.setHtml(_render(stats))
