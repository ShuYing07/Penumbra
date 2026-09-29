# -*- coding: utf-8 -*-
"""隐私与数据管理 Tab（企业版）：GDPR 导出/删除 / 同意记录 / 审计导出。

全部操作本地完成并可审计；删除为事务性且支持 dry-run 预演。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFileDialog, QMessageBox,
                             QTextEdit, QTableWidget, QTableWidgetItem)
from PyQt6.QtCore import Qt

from app.ui.ui_theme import BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB, ACCENT


class PrivacyTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        title = QLabel("🔒 隐私与数据管理（GDPR / CCPA）")
        title.setStyleSheet(f"font-size:15px; font-weight:bold; color:{TEXT_MAIN};")
        lay.addWidget(title)
        tip = QLabel("本地数据处理：导出（可携权）/ 删除（被遗忘权）/ 同意记录 / 审计导出。")
        tip.setStyleSheet(f"color:{TEXT_SUB}; font-size:11px;")
        lay.addWidget(tip)

        # 政策版本
        self.policy_label = QLabel("")
        self.policy_label.setStyleSheet(f"color:{ACCENT}; font-weight:bold;")
        lay.addWidget(self.policy_label)

        row = QHBoxLayout()
        btn_export = QPushButton("📦 导出我的数据 (JSON)")
        btn_export.setStyleSheet(f"background:{ACCENT}; color:#0A0E17; border-radius:6px; padding:8px 14px;")
        btn_export.clicked.connect(self._export)
        row.addWidget(btn_export)

        btn_delete = QPushButton("🗑️ 删除我的数据（预演）")
        btn_delete.clicked.connect(self._delete_dry)
        row.addWidget(btn_delete)

        btn_delete_real = QPushButton("⚠️ 删除我的数据（执行）")
        btn_delete_real.setStyleSheet(
            "background:#FFA726; color:#0A0C10; border-radius:6px; padding:8px 14px;")
        btn_delete_real.clicked.connect(self._delete_real)
        row.addWidget(btn_delete_real)

        btn_audit = QPushButton("📄 导出审计日志 (CSV)")
        btn_audit.clicked.connect(self._export_audit)
        row.addWidget(btn_audit)
        lay.addLayout(row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px;"
            f" color:{TEXT_MAIN};")
        lay.addWidget(self.log, 1)

        lay.addWidget(QLabel("同意记录"))
        self.consent_table = QTableWidget(0, 3)
        self.consent_table.setStyleSheet(
            f"QTableWidget {{ background:{BG_CARD}; border:1px solid {BORDER};"
            f" border-radius:8px; color:{TEXT_MAIN}; gridline-color:{BORDER}; }}")
        lay.addWidget(self.consent_table)
        self.refresh()

    def refresh(self) -> None:
        from core.privacy_compliance import policy_current, consent_history
        pc = policy_current()
        self.policy_label.setText(
            f"隐私政策版本：v{pc['version']}（更新于 {pc['updated_at']}）")
        records = consent_history("local")
        self.consent_table.setColumnCount(3)
        self.consent_table.setHorizontalHeaderLabels(["版本", "动作", "时间"])
        self.consent_table.setRowCount(len(records))
        for i, r in enumerate(records):
            for j, v in enumerate([r["version"], r["action"], r["accepted_at"][:19]]):
                self.consent_table.setItem(i, j, QTableWidgetItem(str(v)))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存导出文件", "gdpr_export.json",
                                              "JSON (*.json)")
        if not path:
            return
        from core.privacy_compliance import export_user_data
        snap = export_user_data("local", out_path=path)
        self.log.append(
            f"✅ 已导出：{snap['total_rows']} 行，{len(snap['databases'])} 个数据库"
            f" → {path}")

    def _delete_dry(self) -> None:
        from core.privacy_compliance import delete_user_data
        r = delete_user_data("local", dry_run=True)
        self.log.append(
            f"🔎 预演：将删除 {r['removed_rows']} 行（{len(r['databases'])} 个库）")

    def _delete_real(self) -> None:
        from core.privacy_compliance import delete_user_data
        ans = QMessageBox.question(
            self, "确认删除",
            "这将删除全部本地数据（分析历史、决策、缓存），不可撤销！\n\n确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        r = delete_user_data("local", dry_run=False)
        self.log.append(f"🗑️ 已删除 {r['removed_rows']} 行（审计已留痕）")

    def _export_audit(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存审计日志", "audit_export.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        from core.audit_logger import export_csv
        out = export_csv(path)
        self.log.append(f"📄 审计日志已导出 → {out}")
