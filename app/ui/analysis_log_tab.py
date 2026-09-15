# -*- coding: utf-8 -*-
"""分析日志标签页：历史 AI 分析记录列表 + 详情查看 + 导出。"""
from __future__ import annotations

import csv

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTextEdit,
    QVBoxLayout, QWidget,
)


class AnalysisLogTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("历史 AI 分析记录："))
        self.b_refresh = QPushButton("刷新")
        self.b_refresh.clicked.connect(self.refresh)
        top.addWidget(self.b_refresh)
        self.b_export = QPushButton("导出日志")
        self.b_export.clicked.connect(self._export)
        top.addWidget(self.b_export)
        top.addWidget(QLabel("  股票："))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("如 600519")
        self.code_input.setMaximumWidth(100)
        top.addWidget(self.code_input)
        self.b_note = QPushButton("添加笔记")
        self.b_note.clicked.connect(self._add_note)
        top.addWidget(self.b_note)
        self.b_review = QPushButton("生成复盘")
        self.b_review.clicked.connect(self._review)
        top.addWidget(self.b_review)
        self.b_report = QPushButton("导出报告")
        self.b_report.clicked.connect(self._export_report)
        top.addWidget(self.b_report)
        top.addStretch(1)
        lay.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show_detail)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.list)
        split.addWidget(self.detail)
        split.setSizes([380, 620])
        lay.addWidget(split)

        self._rows: list[dict] = []
        self.refresh()

    def refresh(self) -> None:
        try:
            from decision_logger import get_decision_history
            self._rows = get_decision_history(limit=100)
        except Exception as e:  # noqa: BLE001
            self._rows = []
            self.detail.setText(f"读取日志失败：{e}")
            return
        self.list.clear()
        for r in self._rows:
            conf = r.get("confidence_score")
            conf_txt = f"{conf:.0f}" if isinstance(conf, (int, float)) else "—"
            label = (f"[{r.get('timestamp', '')[:16]}] {r.get('stock_name') or ''}"
                     f"({r.get('stock_code', '')}) · {r.get('analysis_type', '')}"
                     f" · 置信{conf_txt}")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, r.get("id"))
            self.list.addItem(item)

    def _show_detail(self, row: int) -> None:
        if row < 0:
            return
        try:
            from decision_logger import get_decision_detail
            log_id = self.list.item(row).data(Qt.ItemDataRole.UserRole)
            d = get_decision_detail(log_id)
        except Exception as e:  # noqa: BLE001
            self.detail.setText(f"读取详情失败：{e}")
            return
        if not d:
            self.detail.setText("（无记录）")
            return
        parts = [
            f"时间：{d.get('timestamp')}",
            f"股票：{d.get('stock_name')}({d.get('stock_code')})",
            f"模型：{d.get('model_used')}　类型：{d.get('analysis_type')}　"
            f"置信：{d.get('confidence_score')}",
            f"数据来源：{d.get('data_sources') or '—'}",
            "", "——— 原始输出 ———",
            d.get("raw_output", ""),
        ]
        self.detail.setText("\n".join(parts))

    def _export(self) -> None:
        fmt, ok = QFileDialog.getSaveFileName(
            self, "导出分析日志", "analysis_log.csv", "CSV (*.csv);;JSON (*.json)")
        if not ok or not fmt:
            return
        try:
            from decision_logger import export_decision_log
            content = export_decision_log(fmt="csv" if fmt.lower().endswith("csv") else "json")
            with open(fmt, "w", encoding="utf-8-sig", newline="") as f:
                f.write(content)
            QMessageBox.information(self, "导出成功", f"已保存到：\n{fmt}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(e))

    # ---- 研究笔记 / 复盘 / 报告导出 ----
    def _code(self) -> str:
        return self.code_input.text().strip() or (
            self._rows[0]["stock_code"] if self._rows else "")

    def _add_note(self) -> None:
        code = self._code()
        if not code:
            QMessageBox.information(self, "提示", "请先输入股票代码。")
            return
        note, ok = QInputDialog.getMultiLineText(self, "添加研究笔记", f"{code} 笔记内容：")
        if ok and note.strip():
            from core.research_journal import save_research_note
            save_research_note(code, note.strip())
            QMessageBox.information(self, "已保存", f"笔记已记录到 {code}。")

    def _review(self) -> None:
        code = self._code()
        if not code:
            QMessageBox.information(self, "提示", "请先输入股票代码。")
            return
        from core.research_journal import generate_review_report
        r = generate_review_report(code, 30)
        dist = r["confidence_distribution"]
        txt = [f"复盘报告 · {code}（近{r['days']}天）",
               f"分析次数：{r['analysis_count']}，笔记数：{r['note_count']}",
               f"置信度分布：{dist}", ""]
        for n in r["notes"]:
            txt.append(f"[{n['ts'][:16]}] {n['note']}（标签：{n['tags']}）")
        self.detail.setText("\n".join(txt))

    def _export_report(self) -> None:
        code = self._code()
        if not code:
            QMessageBox.information(self, "提示", "请先输入股票代码。")
            return
        fmt, ok = QInputDialog.getItem(
            self, "导出报告", "格式：", ["Markdown", "HTML"], 0, False)
        if not ok:
            return
        from core.report_generator import export_report
        path = export_report(code, {"stock_name": code},
                              fmt="html" if fmt == "HTML" else "md")
        QMessageBox.information(self, "导出成功", f"报告已保存到：\n{path}")
