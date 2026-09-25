# -*- coding: utf-8 -*-
"""内置定时学习：轻量QTimer+后台线程，不占用CPU。"""
from __future__ import annotations

from datetime import datetime
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer

# 每天这几个点自动学习
LEARN_HOURS = {9, 17, 20}


class _LearnWorker(QThread):
    """后台学习线程，跑完自动退出，不占CPU。"""
    done = pyqtSignal(str)

    def run(self):
        try:
            from auto_train import learn_once
            stats = learn_once()
            self.done.emit(f"学习完成: {stats['fetched']}条新闻")
        except Exception as e:
            self.done.emit(f"学习失败: {e}")


class AutoTrainScheduler(QObject):
    """程序内置的轻量定时学习器。"""
    status_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_run_date = ""  # 避免同一天重复跑
        self._worker = None

        # 每60分钟检查一次（不是每分钟，省CPU）
        self._timer = QTimer(self)
        self._timer.setInterval(60 * 60 * 1000)  # 1小时
        self._timer.timeout.connect(self._check)
        self._timer.start()
        # 启动5分钟后先检查一次
        QTimer.singleShot(5 * 60 * 1000, self._check)

    def _check(self):
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # 不是学习时间，跳过
        if now.hour not in LEARN_HOURS:
            return
        # 今天这个点已经跑过，跳过
        if self._last_run_date == f"{today}_{now.hour}":
            return

        self._last_run_date = f"{today}_{now.hour}"
        self.status_changed.emit(f"开始自动学习 ({now.strftime('%H:%M')})...")

        # 后台线程跑
        self._worker = _LearnWorker()
        self._worker.done.connect(self.status_changed.emit)
        self._worker.start()
