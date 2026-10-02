# -*- coding: utf-8 -*-
"""市场情绪标签页（模块七 · 参考九章·ALGOR 恐惧贪婪/五维情绪/世界指数）。

- 恐惧贪婪指数仪表（0=极度恐惧 → 100=极度贪婪，色阶蓝→红）；
- 五维情绪条（涨跌家数/量能/北向资金/波动率/换手，-100~100 正=乐观）；
- 全球主要指数表格（A股惯例红涨绿跌）。

数据经 core.market_sentiment 聚合；统计字段缺失时自动降级中性，
在线指数获取失败时显示静态参考值并标注「数据可能延迟」。
"""
from __future__ import annotations

import logging
import socket
import threading

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from core.market_sentiment import (fear_greed_index, five_dimension_sentiment,
                                   global_indices)

log = logging.getLogger("stockai.ui.marketsentiment")

# 恐惧贪婪色阶（蓝=恐惧 → 红=贪婪）
_FG_COLORS = ["#1E88E5", "#42A5F5", "#90CAF9", "#B0BEC5", "#FFE082",
              "#FFB74D", "#FF7043", "#E53935"]
_DIM_ORDER = ["涨跌家数", "量能", "北向资金", "波动率", "换手率"]


def _fg_color(idx: float) -> str:
    """指数 → 色阶（0 蓝 → 100 红）。"""
    pos = max(0, min(7, int(idx // 12.5)))
    return _FG_COLORS[pos]


def _fetch_indices_async(on_done) -> None:
    """守护线程拉取全球指数，完成后经 QTimer 回 UI 线程。

    使用标准库 threading(daemon=True) 而非 QThread：避免窗口销毁时
    「QThread destroyed while running」崩溃（0xC0000409）；网络挂起
    时也不阻塞进程退出。socket 超时 8s 保证线程必然快速结束。
    """

    def _run() -> None:
        socket.setdefaulttimeout(8)
        try:
            result = global_indices(fetch=True)
        except Exception as e:  # noqa: BLE001
            result = {"rows": [], "stale": True, "source": "error",
                      "note": f"获取失败：{e}"}
        QTimer.singleShot(0, lambda: on_done(result))

    threading.Thread(target=_run, daemon=True).start()


class MarketSentimentTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        # 顶栏：刷新按钮 + 数据源状态
        top = QHBoxLayout()
        self.btn_refresh = QPushButton("🔄 刷新情绪数据")
        self.btn_refresh.clicked.connect(self.refresh)
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#8B949E;")
        top.addWidget(self.btn_refresh)
        top.addWidget(self.lbl_status)
        top.addStretch(1)
        lay.addLayout(top)

        # 恐惧贪婪仪表
        fg = QVBoxLayout()
        fg_lbl = QLabel("恐惧贪婪指数")
        fg_lbl.setStyleSheet("font-size:14px;color:#DCE1EB;font-weight:bold;")
        self.fg_bar = QProgressBar()
        self.fg_bar.setRange(0, 100)
        self.fg_bar.setFixedHeight(26)
        self.fg_bar.setTextVisible(True)
        self.fg_lbl_value = QLabel("--")
        self.fg_lbl_value.setStyleSheet("font-size:20px;color:#DCE1EB;font-weight:bold;")
        fg.addWidget(fg_lbl)
        fg.addWidget(self.fg_bar)
        fg.addWidget(self.fg_lbl_value)
        lay.addLayout(fg)

        # 五维情绪条
        dims = QVBoxLayout()
        dims_lbl = QLabel("五维情绪")
        dims_lbl.setStyleSheet("font-size:14px;color:#DCE1EB;font-weight:bold;")
        dims.addWidget(dims_lbl)
        self.dim_bars: dict[str, QProgressBar] = {}
        self.dim_values: dict[str, QLabel] = {}
        for d in _DIM_ORDER:
            row = QHBoxLayout()
            name = QLabel(d)
            name.setFixedWidth(72)
            bar = QProgressBar()
            bar.setRange(-100, 100)
            bar.setFormat("%v")
            self.dim_bars[d] = bar
            val = QLabel("--")
            val.setFixedWidth(64)
            val.setStyleSheet("color:#8B949E;")
            self.dim_values[d] = val
            row.addWidget(name)
            row.addWidget(bar, 1)
            row.addWidget(val)
            dims.addLayout(row)
        lay.addLayout(dims)

        # 全球指数表格
        idx_lbl = QLabel("全球主要指数")
        idx_lbl.setStyleSheet("font-size:14px;color:#DCE1EB;font-weight:bold;")
        lay.addWidget(idx_lbl)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["代码", "名称", "市场", "最新点位", "涨跌幅"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(4, 90)
        lay.addWidget(self.table, 1)

        self._fetching = False
        QTimer.singleShot(0, self.refresh)

    def _render_fg(self, fg: dict) -> None:
        idx = float(fg.get("index", 50.0))
        self.fg_bar.setValue(int(round(idx)))
        color = _fg_color(idx)
        self.fg_bar.setStyleSheet(
            f"QProgressBar{{border:1px solid #1E2530;border-radius:4px;"
            f"background:#0D1117;text-align:center;}}"
            f"QProgressBar::chunk{{background:{color};}}")
        note = fg.get("note", "")
        level = fg.get("level", "")
        self.fg_lbl_value.setText(
            f"{idx:.1f} · {level}"
            + (f"<span style='color:#FFA726;font-size:12px'>（{note}）</span>"
               if note else ""))

    def _render_dims(self, five: dict) -> None:
        dims = five.get("dimensions", {})
        for d in _DIM_ORDER:
            bar = self.dim_bars[d]
            if d in dims:
                v = float(dims[d])
                bar.setValue(int(round(v)))
                color = "#E53935" if v > 0 else "#1E88E5" if v < 0 else "#B0BEC5"
                bar.setStyleSheet(
                    f"QProgressBar{{border:1px solid #1E2530;border-radius:4px;"
                    f"background:#0D1117;text-align:center;}}"
                    f"QProgressBar::chunk{{background:{color};}}")
                self.dim_values[d].setText(f"{v:+.0f}")
            else:
                bar.setValue(0)
                bar.setStyleSheet("")
                self.dim_values[d].setText("--")

    def _render_indices(self, gi: dict) -> None:
        rows = gi.get("rows", [])
        stale = gi.get("stale", True)
        note = gi.get("note", "")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            pct = float(r.get("change_pct", 0) or 0)
            color = "#E53935" if pct > 0 else "#1E88E5" if pct < 0 else "#B0BEC5"
            vals = [str(r.get("code", "")), str(r.get("name", "")),
                    str(r.get("market", "")), f"{float(r.get('last', 0)):,.2f}",
                    f"{pct:+.2f}%"]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 4:
                    it.setForeground(QColor(color))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, j, it)
        self.lbl_status.setText(
            (f"{note}　共 {len(rows)} 个指数"
             + ("　⚠️ 数据可能延迟" if stale else "　🟢 实时")))

    def refresh(self) -> None:
        # 情绪统计（离线/降级安全）：涨跌家数等缺失时自动中性
        stats = {}
        try:
            from core.data.data_bus import snapshot_market_stats  # 可选
            stats = snapshot_market_stats() or {}
        except Exception:  # noqa: BLE001
            stats = {}
        fg = fear_greed_index(stats)
        five = five_dimension_sentiment(stats)
        self._render_fg(fg)
        self._render_dims(five)
        # 全球指数：守护线程拉实时，失败自动降级静态
        if self._fetching:
            return
        self._fetching = True
        _fetch_indices_async(lambda r: (self._render_indices(r),
                                        setattr(self, "_fetching", False)))
