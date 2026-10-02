# -*- coding: utf-8 -*-
"""本地模型管理对话框（2026-10 升级）：
- 模型清单升级到 2026 前沿（Ling-3.0-flash-Fin / Qwen3-14B / Qwen3-VL / Amsi-fin-o1）；
- 实时探测 Ollama 已安装模型 + 云端 AI 引擎状态；
- 「一键复制安装命令」引导（绝不自动执行安装，红线约束）。
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
                             QHBoxLayout, QLabel, QProgressBar, QPushButton,
                             QVBoxLayout)

from core import llm_local
from core import model_router
from core.config import LOCAL_MODEL, LOCAL_MODEL_SMALL

# 2026-10 前沿模型清单（Ollama 标签名）
_MODELS = [
    ("Ling-3.0-flash-Fin（金融增强 · Finance Agent v2 榜首，约 78GB，24GB+ 显存）",
     "ling-3.0-flash-fin"),
    ("Qwen3-14B（本地综合最佳，Q4 约 9GB，12-16GB 显存）", "qwen3:14b"),
    ("Qwen3-VL-7B（视觉：K线图/财报截图/票据）", "qwen3-vl:7b"),
    ("Amsi-fin-o1（金融视觉语言模型，可选）", "amsi-fin-o1"),
    ("Qwen2.5-7B（兼容低配，约 4.7GB）", LOCAL_MODEL),
    ("Qwen2.5-3B（低配/纯CPU，约 2.0GB）", LOCAL_MODEL_SMALL),
]


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
        self.setWindowTitle("本地模型管理（Ollama）· AI 引擎")
        self.setMinimumWidth(620)
        self.worker: PullWorker | None = None
        self._build()
        self.refresh_status()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        self.lbl_status = QLabel("检测中…")
        self.lbl_status.setWordWrap(True)
        v.addWidget(self.lbl_status)

        # ---- AI 引擎状态（云端可用平台 + 本地已装模型）----
        self.lbl_engine = QLabel("")
        self.lbl_engine.setWordWrap(True)
        self.lbl_engine.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.lbl_engine)

        # ---- 模型清单 ----
        row = QHBoxLayout()
        row.addWidget(QLabel("模型："))
        self.model_box = QComboBox()
        for label, _ in _MODELS:
            self.model_box.addItem(label)
        row.addWidget(self.model_box, 1)
        v.addLayout(row)

        self.btn_pull = QPushButton("下载选中模型（约数 GB，耐心等待）")
        self.btn_pull.clicked.connect(self._pull)
        v.addWidget(self.btn_pull)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        v.addWidget(self.bar)
        self.lbl_progress = QLabel("")
        v.addWidget(self.lbl_progress)

        # ---- 推荐安装命令（一键复制，绝不自动执行）----
        self.lbl_cmd = QLabel("")
        self.lbl_cmd.setWordWrap(True)
        self.lbl_cmd.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.lbl_cmd)
        btn_copy = QPushButton("复制安装命令到剪贴板")
        btn_copy.clicked.connect(self._copy_cmd)
        v.addWidget(btn_copy)

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

        v.addWidget(QLabel(
            "说明：模型由 Ollama 统一管理、完全离线零费用。Ling-3.0-flash-Fin 是"
            "蚂蚁百灵开源金融增强模型（Finance Agent v2 排行榜第一，MIT 协议），"
            "财报/估值/多文档金融分析最佳；机器配置有限时建议 Qwen3-14B。"))
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
        self._refresh_engine()

    def _refresh_engine(self) -> None:
        st = model_router.engine_status()
        cloud = "、".join(st["cloud_ready"]) or "未配置（可在设置页填写 API Key）"
        installed = "、".join(st["local_installed"]) or "无"
        missing = "、".join(st["recommended_missing"]) or "（已齐）"
        self.lbl_engine.setText(
            f"<b>☁️ 云端引擎（已就绪）：</b>{cloud}<br>"
            f"<b>💻 本地已装模型：</b>{installed}<br>"
            f"<b>📥 推荐未装：</b>{missing}")
        if st["recommended_missing"]:
            first = st["recommended_missing"][0]
            pull = next((m["pull"] for m in model_router.recommended_local_models()
                         if m["name"] == first), "")
            self.lbl_cmd.setText(f"推荐先装：{first}\n复制命令后在终端执行：{pull}")
        else:
            self.lbl_cmd.setText("")

    def _copy_cmd(self) -> None:
        m = self.current_model
        pull = next((x["pull"] for x in model_router.recommended_local_models()
                     if x["name"] == m), f"ollama pull {m}")
        QApplication.clipboard().setText(pull)
        self.lbl_status.setText(f"已复制：{pull}（请在你的终端手动执行，程序不自动安装）")

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
            # 运行期指定刚下载的模型（金融任务路由也会探测到它）
            os.environ["STOCKAI_LOCAL_MODEL"] = self.current_model
            self.model_changed.emit()

    def _open_training(self) -> None:
        from app.ui.training_dialog import TrainingDialog
        dlg = TrainingDialog(self)
        dlg.model_changed.connect(self.model_changed.emit)
        dlg.exec()
