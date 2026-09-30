# -*- coding: utf-8 -*-
"""合规审计标签页：查看审计记录 + 多管辖区监管验证 + 导出。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)


class ComplianceAuditTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("合规审计记录："))
        self.b_refresh = QPushButton("刷新")
        self.b_refresh.clicked.connect(self.refresh)
        top.addWidget(self.b_refresh)
        top.addWidget(QLabel("管辖区"))
        self.cmb_jur = QComboBox()
        for j in ("GLOBAL", "CN", "US", "EU", "UK", "SG", "HK"):
            self.cmb_jur.addItem(j)
        self.cmb_jur.currentTextChanged.connect(self.refresh)
        top.addWidget(self.cmb_jur)
        self.b_validate = QPushButton("监管验证")
        self.b_validate.clicked.connect(self._validate)
        top.addWidget(self.b_validate)
        self.b_export = QPushButton("导出审计日志")
        self.b_export.clicked.connect(self._export)
        top.addWidget(self.b_export)
        top.addStretch(1)
        lay.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.list)
        split.addWidget(self.detail)
        split.setSizes([380, 620])
        lay.addWidget(split)
        self._rows = []
        self.refresh()

    def refresh(self) -> None:
        try:
            from core.audit_trail import list_audit
            self._rows = list_audit(limit=100)
        except Exception as e:  # noqa: BLE001
            self._rows = []
            self.detail.setText(f"读取失败：{e}")
            return
        self.list.clear()
        for r in self._rows:
            label = (f"[{r.get('ts', '')[:16]}] {r.get('filter_result','')} · "
                     f"{r.get('model_name','')} · {r.get('filter_details','')}")
            self.list.addItem(QListWidgetItem(label))

    def _validate(self) -> None:
        """对审计记录跑多管辖区监管验证，展示分级报告。"""
        jur = self.cmb_jur.currentText()
        try:
            from security.regulatory_validator import compliance_report
            records = []
            for r in self._rows:
                records.append({
                    "content": r.get("filter_details", "") + " "
                               + r.get("filter_result", ""),
                    "position_pct": 0.1, "transfers": [],
                    "threshold": 10000, "day": "1",
                    "unpublished": [],
                })
            rpt = compliance_report(records, [jur])
            lines = [rpt["summary"], ""]
            for f in rpt["failures"][:20]:
                lines.append(f"[{f['severity']}] {f['rule_id']}"
                             f"（{f['jurisdiction']}/{f['category']}）："
                             f"{f['message']}")
            if not rpt["failures"]:
                lines.append("未发现违规项。")
            self.detail.setPlainText("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            self.detail.setPlainText(f"监管验证失败：{e}")

    def _export(self) -> None:
        try:
            from core.audit_trail import export_audit
            from pathlib import Path
            out = Path.home() / "audit_export.json"
            out.write_text(export_audit(), encoding="utf-8")
            QMessageBox.information(self, "导出成功", f"已保存到：\n{out}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(e))
