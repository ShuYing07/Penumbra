# -*- coding: utf-8 -*-
"""系统健康面板（任务书A·模块三）：启动耗时 / 内存占用 / 模块加载时间 / API 调用次数 / 数据源延迟。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (QLabel, QTextEdit, QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.health")


class HealthTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        lay.addWidget(self.out, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(5000)  # 每 5 秒刷新

    def _refresh(self) -> None:
        try:
            from core.performance_monitor import perf
            sn = perf.get_snapshot()
            anomalies = perf.check_anomalies()
        except Exception as e:  # noqa: BLE001
            self.out.setText(f"性能监控不可用：{e}")
            return
        mem = sn.get("memory_mb")
        mods = sn.get("modules", {})
        api = sn.get("api_calls", {})
        lines = [
            "<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>",
            "<h2>🩺 系统健康</h2>",
            f"<p>运行时长：<b>{sn.get('uptime_s', 0):.0f}s</b>　"
            f"内存：<b>{mem if mem is not None else 'N/A'} MB</b>　"
            f"启动耗时：<b>{sn.get('startup_ms', 0) / 1000:.2f}s</b></p>",
            "<h3>API 调用统计</h3><table style='border-collapse:collapse;width:100%'>",
        ]
        for k, v in sorted(api.items()):
            lines.append(
                f"<tr><td style='border:1px solid #1E2530;padding:6px;color:#8B949E'>{k}</td>"
                f"<td style='border:1px solid #1E2530;padding:6px'>{v}</td></tr>")
        if not api:
            lines.append("<tr><td style='padding:6px;color:#8B949E'>暂无 API 调用记录</td></tr>")
        lines.append("</table><h3>模块加载时间（ms）</h3>"
                     "<table style='border-collapse:collapse;width:100%'>")
        for k, m in sorted(mods.items(), key=lambda x: -x[1]["total_ms"]):
            lines.append(
                f"<tr><td style='border:1px solid #1E2530;padding:6px;color:#8B949E'>{k}</td>"
                f"<td style='border:1px solid #1E2530;padding:6px'>{m['calls']} 次 / "
                f"累计 {m['total_ms']:.0f} / 最近 {m['last_ms']:.0f} / 最大 {m['max_ms']:.0f}</td></tr>")
        lines.append("</table>")
        if anomalies:
            lines.append("<h3 style='color:#FFA726'>⚠️ 异常提示</h3><ul>")
            for a in anomalies:
                lines.append(f"<li style='color:#FFA726'>{a}</li>")
            lines.append("</ul>")
        else:
            lines.append("<p style='color:#00C853'>✅ 各项指标正常</p>")
        lines.append("</div>")
        self.out.setHtml("".join(lines))
