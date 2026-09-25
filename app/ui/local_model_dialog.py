# -*- coding: utf-8 -*-
"""本地模型管理对话框：Ollama 状态检测、模型下载（进度条）、安装指引。"""
from __future__ import annotations

import os

from PyQt6.QtCore import QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QProgressBar, QPushButton, QVBoxLayout)

from core import llm_local
from core.config import LOCAL_MODEL, LOCAL_MODEL_SMALL

_MODELS = [("Qwen2.5-7B（推荐，中文好，约 4.7GB，8GB 显存）", LOCAL_MODEL),
           ("Qwen2.5-3B（低配/纯CPU，约 2.0GB，速度快）", LOCAL_MODEL_SMALL)]


class PullWorker(QThread):
    progress = pyqtSignal(int, str)
    done = pyqtSignal(bool, str)

    def __init__(self, model: str, parent=None):
        super().__init__(parent)
        self.model = model

    def run(self) -> None:
        ok, msg = llm_local.ensure_model(
            self.model, progress_cb=lambda pct, text: self.progress.emit(pct, text))
        self.done.emit(ok, msg)


class LocalModelDialog(QDialog):
    model_changed = pyqtSignal()  # 下载成功后通知外部刷新

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("本地模型管理（Ollama）")
        self.setMinimumWidth(520)
        self.worker: PullWorker | None = None
        self._build()
        self.refresh_status()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        self.lbl_status = QLabel("检测中…")
        self.lbl_status.setWordWrap(True)
        v.addWidget(self.lbl_status)

        row = QHBoxLayout()
        row.addWidget(QLabel("模型："))
        self.model_box = QComboBox()
        for label, _ in _MODELS:
            self.model_box.addItem(label)
        row.addWidget(self.model_box, 1)
        v.addLayout(row)

        self.btn_pull = QPushButton("下载选中模型")
        self.btn_pull.clicked.connect(self._pull)
        v.addWidget(self.btn_pull)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        v.addWidget(self.bar)
        self.lbl_progress = QLabel("")
        v.addWidget(self.lbl_progress)

        row2 = QHBoxLayout()
        btn_install = QPushButton("安装 Ollama（打开官网）")
        btn_install.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://ollama.com/download/windows")))
        row2.addWidget(btn_install)
        btn_recheck = QPushButton("重新检测")
        btn_recheck.clicked.connect(self.refresh_status)
        row2.addWidget(btn_recheck)
        row2.addStretch()
        v.addLayout(row2)

        row3 = QHBoxLayout()
        self.btn_train = QPushButton("训练离线模型…（教学资源蒸馏）")
        self.btn_train.clicked.connect(self._open_training)
        row3.addWidget(self.btn_train)
        row3.addStretch()
        v.addLayout(row3)

        v.addWidget(QLabel("说明：模型仅下载一次（Ollama 统一管理）；推理完全离线、零费用；"
                           "RTX 5060 上 7B 约每秒数十 token。"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_btn.clicked.connect(self.reject)
        v.addWidget(buttons)

    @property
    def current_model(self) -> str:
        return _MODELS[self.model_box.currentIndex()][1]

    def refresh_status(self) -> None:
        self.lbl_status.setText(llm_local.status_text())

    def _pull(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        if not llm_local.is_installed():
            self.lbl_status.setText("未检测到 Ollama，请先点『安装 Ollama』，装完点『重新检测』")
            return
        if not llm_local.ensure_started():
            self.lbl_status.setText("Ollama 服务启动失败，请从开始菜单启动 Ollama 后重试")
            return
        self.btn_pull.setEnabled(False)
        self.bar.setValue(0)
        self.lbl_progress.setText(f"开始下载 {self.current_model}（约数 GB，请耐心等待）…")
        self.worker = PullWorker(self.current_model)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    @pyqtSlot(int, str)
    def _on_progress(self, pct: int, text: str) -> None:
        if pct >= 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(pct)
        else:
            self.bar.setRange(0, 0)  # 不确定进度（校验/解压阶段）
        self.lbl_progress.setText(text)

    @pyqtSlot(bool, str)
    def _on_done(self, ok: bool, msg: str) -> None:
        self.btn_pull.setEnabled(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if ok else self.bar.value())
        self.lbl_progress.setText(("✅ " if ok else "❌ ") + msg)
        self.refresh_status()
        if ok:
            # 运行期指定刚下载的模型（3B/7B 都可），LLMRunner 会读此变量
            os.environ["STOCKAI_LOCAL_MODEL"] = self.current_model
            self.model_changed.emit()

    def _open_training(self) -> None:
        from app.ui.training_dialog import TrainingDialog
        dlg = TrainingDialog(self)
        dlg.model_changed.connect(self.model_changed.emit)
        dlg.exec()
