# -*- coding: utf-8 -*-
"""训练离线模型对话框：资源获取 → 教师蒸馏 → QLoRA 训练 → 导入 Ollama。

四步全后台线程+进度，训练耗时长不卡界面。
训练在独立 venv_train（Python 3.11）执行，主 venv/打包不含 torch。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                             QTextBrowser, QTabWidget, QVBoxLayout, QWidget)

from core.config import LOCAL_MODEL
from core.training import curriculum, distill, ollama_import, resources

MODEL_NAME = "stockai-qwen-curriculum"


class FetchWorker(QThread):
    progress = pyqtSignal(int, str)
    done = pyqtSignal(bool, str)

    def __init__(self, source_ids: list[str], parent=None):
        super().__init__(parent)
        self.source_ids = source_ids

    def run(self) -> None:
        if not self.source_ids:
            self.done.emit(False, "未选择资源源"); return
        ok_n = 0
        for i, sid in enumerate(self.source_ids):
            self.progress.emit(int(i / len(self.source_ids) * 100), f"获取 {sid} …")
            ok, _, _ = resources.fetch_and_parse(
                sid, progress_cb=lambda p, t, _sid=sid: self.progress.emit(p, f"{_sid}: {t}"))
            if ok:
                ok_n += 1
        self.done.emit(ok_n == len(self.source_ids), f"{ok_n}/{len(self.source_ids)} 成功")


class DistillWorker(QThread):
    progress = pyqtSignal(int, str)
    done = pyqtSignal(bool, str)

    def run(self) -> None:
        from core.llm import LLMRunner
        try:
            runner = LLMRunner(backend="local")
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, f"本地模型不可用：{e}"); return
        r = curriculum.distill_corpus(runner=runner,
                                      progress_cb=lambda p, m: self.progress.emit(p, m))
        self.done.emit(r["written"] > 0,
                       f"写入 {r['written']} 对（跳过 {r['skipped']} 块，{r['files']} 文件）")


class TrainWorker(QThread):
    output_line = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        venv = ollama_import.find_venv_train()
        if not venv:
            self.done.emit(False, "未找到 venv_train，先跑 scripts\\bootstrap_venv_train.ps1"); return
        self.output_line.emit(f"venv_train: {venv}")
        ok, msg = ollama_import.stop_local_model()
        self.output_line.emit(msg)
        yaml = (ollama_import.PROJECT_ROOT / "training_configs" /
                "qwen2_5_qlora_curriculum.yaml").resolve()
        rc = ollama_import.run_training(yaml, venv, on_line=self.output_line.emit,
                                        stop_check=lambda: self._stop)
        self.done.emit(rc == 0, f"训练退出码 {rc}" + ("（已停止）" if self._stop else ""))


class ImportWorker(QThread):
    output_line = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, model_name: str, parent=None):
        super().__init__(parent)
        self.model_name = model_name

    def run(self) -> None:
        venv = ollama_import.find_venv_train()
        if not venv:
            self.done.emit(False, "未找到 venv_train"); return
        root = ollama_import.PROJECT_ROOT
        merge_yaml = (root / "training_configs" / "merge_lora.yaml").resolve()
        ok, msg, _ = ollama_import.merge_lora(merge_yaml, venv, on_line=self.output_line.emit)
        if not ok:
            self.done.emit(False, msg); return
        mf = (root / "training_configs" / "Modelfile.stockai").resolve()
        ok, msg = ollama_import.ollama_create(self.model_name, mf, on_line=self.output_line.emit)
        if not ok:
            self.done.emit(False, msg); return
        ollama_import.set_local_model(self.model_name, persist=True)
        self.done.emit(True, f"已导入并设为本地模型：{self.model_name}")


class TrainingDialog(QDialog):
    model_changed = pyqtSignal()  # 导入新模型后通知外部刷新

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("训练离线模型（教学资源蒸馏）")
        self.setMinimumSize(640, 520)
        self.fetch_worker: FetchWorker | None = None
        self.distill_worker: DistillWorker | None = None
        self.train_worker: TrainWorker | None = None
        self.import_worker: ImportWorker | None = None
        self._build()
        self._refresh_corpus()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        tabs = QTabWidget()

        # ---- 资源页 ----
        res_tab = QWidget()
        rv = QVBoxLayout(res_tab)
        rv.addWidget(QLabel("内置开放许可资源源（勾选后获取，自动解析为纯文本）："))
        self.src_list = QListWidget()
        for s in resources.list_sources():
            it = QListWidgetItem(f"[{s.id}] {s.name}  ({s.kind}/{s.language}/{s.license})  {','.join(s.topics)}")
            it.setData(Qt.ItemDataRole.UserRole, s.id)
            it.setCheckState(Qt.CheckState.Checked)
            self.src_list.addItem(it)
        rv.addWidget(self.src_list, 1)
        row = QHBoxLayout()
        self.btn_fetch = QPushButton("获取选中资源")
        self.btn_fetch.clicked.connect(self._fetch)
        row.addWidget(self.btn_fetch)
        self.btn_corpus_refresh = QPushButton("刷新语料")
        self.btn_corpus_refresh.clicked.connect(self._refresh_corpus)
        row.addWidget(self.btn_corpus_refresh)
        row.addStretch()
        rv.addLayout(row)
        self.fetch_bar = QProgressBar(); self.fetch_bar.setRange(0, 100)
        rv.addWidget(self.fetch_bar)
        self.fetch_lbl = QLabel("")
        self.fetch_lbl.setWordWrap(True)
        rv.addWidget(self.fetch_lbl)
        tabs.addTab(res_tab, "1·资源")

        # ---- 蒸馏页 ----
        dis_tab = QWidget()
        dv = QVBoxLayout(dis_tab)
        dv.addWidget(QLabel(f"本地教师：{LOCAL_MODEL}（完全离线、零费用）"))
        dv.addWidget(QLabel("把教材文本用本地模型生成 Q&A → 落蒸馏语料（source=curriculum）"))
        self.btn_distill = QPushButton("开始蒸馏")
        self.btn_distill.clicked.connect(self._distill)
        dv.addWidget(self.btn_distill)
        self.dis_bar = QProgressBar(); self.dis_bar.setRange(0, 100)
        dv.addWidget(self.dis_bar)
        self.dis_lbl = QLabel("")
        self.dis_lbl.setWordWrap(True)
        dv.addWidget(self.dis_lbl)
        self.dis_stats = QLabel("")
        dv.addWidget(self.dis_stats)
        dv.addStretch()
        tabs.addTab(dis_tab, "2·蒸馏")

        # ---- 训练页 ----
        tr_tab = QWidget()
        tv = QVBoxLayout(tr_tab)
        tv.addWidget(QLabel("QLoRA 4bit 训练（独立 venv_train，8GB 显存保守配置）"))
        self.train_env_lbl = QLabel("")
        tv.addWidget(self.train_env_lbl)
        rowt = QHBoxLayout()
        self.btn_train = QPushButton("启动训练（后台）")
        self.btn_train.clicked.connect(self._train)
        rowt.addWidget(self.btn_train)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self._stop_train)
        self.btn_stop.setEnabled(False)
        rowt.addWidget(self.btn_stop)
        rowt.addStretch()
        tv.addLayout(rowt)
        self.train_log = QTextBrowser()
        tv.addWidget(self.train_log, 1)
        tabs.addTab(tr_tab, "3·训练")

        # ---- 导入页 ----
        imp_tab = QWidget()
        iv = QVBoxLayout(imp_tab)
        iv.addWidget(QLabel("合并 LoRA → 导入 Ollama → 设为本地学生模型"))
        iv.addWidget(QLabel(f"新模型名：{MODEL_NAME}"))
        self.btn_import = QPushButton("合并并导入")
        self.btn_import.clicked.connect(self._import)
        iv.addWidget(self.btn_import)
        self.imp_log = QTextBrowser()
        iv.addWidget(self.imp_log, 1)
        iv.addWidget(QLabel("导入后引擎选『本地』即可使用蒸馏增强模型。"))
        iv.addStretch()
        tabs.addTab(imp_tab, "4·导入")

        v.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)
        self._check_venv()

    # ---- 资源 ----
    def _refresh_corpus(self) -> None:
        st = resources.corpus_stats()
        self.fetch_lbl.setText(f"语料库：{st['files']} 文件 / {st['chars']} 字符")
        self.dis_stats.setText(f"当前语料：{st['files']} 文件。蒸馏语料条数：{distill.stats().get('sft_by_source', {}).get('curriculum', 0)}")

    def _fetch(self) -> None:
        if self.fetch_worker and self.fetch_worker.isRunning():
            return
        ids = [it.data(Qt.ItemDataRole.UserRole) for it in self.src_list.items()
               if it.checkState() == Qt.CheckState.Checked]
        if not ids:
            self.fetch_lbl.setText("请先勾选资源源"); return
        self.btn_fetch.setEnabled(False)
        self.fetch_bar.setValue(0)
        self.fetch_worker = FetchWorker(ids)
        self.fetch_worker.progress.connect(self._on_fetch_progress)
        self.fetch_worker.done.connect(self._on_fetch_done)
        self.fetch_worker.start()

    @pyqtSlot(int, str)
    def _on_fetch_progress(self, pct: int, text: str) -> None:
        if pct >= 0:
            self.fetch_bar.setRange(0, 100); self.fetch_bar.setValue(pct)
        else:
            self.fetch_bar.setRange(0, 0)
        self.fetch_lbl.setText(text)

    @pyqtSlot(bool, str)
    def _on_fetch_done(self, ok: bool, msg: str) -> None:
        self.btn_fetch.setEnabled(True)
        self.fetch_bar.setRange(0, 100); self.fetch_bar.setValue(100 if ok else 0)
        self.fetch_lbl.setText(("✅ " if ok else "❌ ") + msg)
        self._refresh_corpus()

    # ---- 蒸馏 ----
    def _distill(self) -> None:
        if self.distill_worker and self.distill_worker.isRunning():
            return
        if not resources.corpus_files():
            self.dis_lbl.setText("语料库为空，先在『资源』页获取"); return
        self.btn_distill.setEnabled(False)
        self.dis_bar.setValue(0)
        self.distill_worker = DistillWorker()
        self.distill_worker.progress.connect(self._on_dis_progress)
        self.distill_worker.done.connect(self._on_dis_done)
        self.distill_worker.start()

    @pyqtSlot(int, str)
    def _on_dis_progress(self, pct: int, text: str) -> None:
        if pct >= 0:
            self.dis_bar.setRange(0, 100); self.dis_bar.setValue(pct)
        else:
            self.dis_bar.setRange(0, 0)
        self.dis_lbl.setText(text)

    @pyqtSlot(bool, str)
    def _on_dis_done(self, ok: bool, msg: str) -> None:
        self.btn_distill.setEnabled(True)
        self.dis_bar.setRange(0, 100); self.dis_bar.setValue(100 if ok else 0)
        self.dis_lbl.setText(("✅ " if ok else "❌ ") + msg)
        self._refresh_corpus()

    # ---- 训练 ----
    def _check_venv(self) -> None:
        venv = ollama_import.find_venv_train()
        if venv:
            self.train_env_lbl.setText("✅ venv_train: " + str(venv))
        else:
            self.train_env_lbl.setText("❌ 未找到 venv_train，先跑 scripts\\bootstrap_venv_train.ps1")

    def _train(self) -> None:
        if self.train_worker and self.train_worker.isRunning():
            return
        if not ollama_import.find_venv_train():
            self.train_log.append("未找到 venv_train"); return
        if not resources.corpus_files() and not distill.stats().get("sft_by_source", {}).get("curriculum"):
            self.train_log.append("无 curriculum 语料，先在『蒸馏』页生成并导出"); return
        self.btn_train.setEnabled(False); self.btn_stop.setEnabled(True)
        self.train_log.clear()
        self.train_log.append("启动训练（先导出 curriculum 训练集）…")
        try:
            distill.export_llamafactory(sources=("curriculum",))
        except Exception as e:  # noqa: BLE001
            self.train_log.append(f"导出失败：{e}"); self.btn_train.setEnabled(True); self.btn_stop.setEnabled(False); return
        self.train_worker = TrainWorker()
        self.train_worker.output_line.connect(self.train_log.append)
        self.train_worker.done.connect(self._on_train_done)
        self.train_worker.start()

    def _stop_train(self) -> None:
        if self.train_worker:
            self.train_worker.stop()

    @pyqtSlot(bool, str)
    def _on_train_done(self, ok: bool, msg: str) -> None:
        self.train_log.append(("✅ " if ok else "❌ ") + msg)
        self.btn_train.setEnabled(True); self.btn_stop.setEnabled(False)

    # ---- 导入 ----
    def _import(self) -> None:
        if self.import_worker and self.import_worker.isRunning():
            return
        self.btn_import.setEnabled(False)
        self.imp_log.clear()
        self.import_worker = ImportWorker(MODEL_NAME)
        self.import_worker.output_line.connect(self.imp_log.append)
        self.import_worker.done.connect(self._on_import_done)
        self.import_worker.start()

    @pyqtSlot(bool, str)
    def _on_import_done(self, ok: bool, msg: str) -> None:
        self.imp_log.append(("✅ " if ok else "❌ ") + msg)
        self.btn_import.setEnabled(True)
        if ok:
            self.model_changed.emit()
