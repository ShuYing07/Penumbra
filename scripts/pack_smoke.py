# -*- coding: utf-8 -*-
"""打包冒烟最小程序：验证 PyInstaller + PyQt6 工具链。
正常运行显示窗口；--selftest 创建窗口、泵 1 秒事件后退出码 0（供自动化验证）。"""
import sys

from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow
from PyQt6.QtCore import QTimer


class SmokeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StockAIPredictor 打包冒烟")
        self.resize(420, 200)
        self.setCentralWidget(QLabel(
            "PyQt6 + PyInstaller OK\nPython " + sys.version.split()[0], self))
        self.centralWidget().setStyleSheet("font-size:16px; padding:40px;")


def main() -> int:
    app = QApplication(sys.argv)
    win = SmokeWindow()
    win.show()
    if "--selftest" in sys.argv:
        QTimer.singleShot(1000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
