# -*- coding: utf-8 -*-
"""协作空间 Tab（企业版）：共享研究空间 / 评论 / 版本控制。

本地 SQLite（data/collab.db），无网络依赖；与 core/collaboration.py 联动。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QLineEdit, QPushButton, QTextEdit,
                             QComboBox, QSplitter, QMessageBox, QInputDialog)
from PyQt6.QtCore import Qt

from app.ui.ui_theme import BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB, ACCENT


class CollaborationTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_ws: dict | None = None
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        title = QLabel("🤝 协作空间（企业版）")
        title.setStyleSheet(f"font-size:15px; font-weight:bold; color:{TEXT_MAIN};")
        lay.addWidget(title)
        tip = QLabel("共享研究空间：创建空间 → 成员协作 → 评论与版本控制。数据仅存本机。")
        tip.setStyleSheet(f"color:{TEXT_SUB}; font-size:11px;")
        lay.addWidget(tip)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # 左：空间列表 + 操作
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("空间列表"))
        self.ws_list = QListWidget()
        self.ws_list.itemClicked.connect(self._select_ws)
        ll.addWidget(self.ws_list)
        row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("新空间名称")
        row.addWidget(self.name_edit, 1)
        btn_new = QPushButton("创建")
        btn_new.setStyleSheet(f"background:{ACCENT}; color:#0A0E17; border-radius:6px; padding:4px 10px;")
        btn_new.clicked.connect(self._create_ws)
        row.addWidget(btn_new)
        ll.addLayout(row)

        # 右：评论 + 版本
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("评论（选中空间后输入资源，如 SH600519 / strategy:ma_cross）"))
        self.resource_edit = QLineEdit("SH600519")
        rl.addWidget(self.resource_edit)
        self.comments_view = QTextEdit()
        self.comments_view.setReadOnly(True)
        self.comments_view.setStyleSheet(
            f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px; color:{TEXT_MAIN};")
        rl.addWidget(self.comments_view, 1)
        row2 = QHBoxLayout()
        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText("写评论…")
        row2.addWidget(self.comment_edit, 1)
        btn_comment = QPushButton("评论")
        btn_comment.clicked.connect(self._add_comment)
        row2.addWidget(btn_comment)
        rl.addLayout(row2)

        rl.addWidget(QLabel("版本控制（提交 / 回滚）"))
        row3 = QHBoxLayout()
        self.ver_content = QLineEdit()
        self.ver_content.setPlaceholderText("版本内容，如 fast=5,slow=20")
        row3.addWidget(self.ver_content, 1)
        btn_commit = QPushButton("提交版本")
        btn_commit.clicked.connect(self._commit_version)
        row3.addWidget(btn_commit)
        btn_rollback = QPushButton("回滚")
        btn_rollback.clicked.connect(self._rollback)
        row3.addWidget(btn_rollback)
        rl.addLayout(row3)
        self.versions_label = QLabel("")
        self.versions_label.setStyleSheet(f"color:{TEXT_SUB}; font-size:11px;")
        rl.addWidget(self.versions_label)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([260, 600])
        lay.addWidget(splitter, 1)
        self.refresh()

    # ---------------- 数据 ----------------
    def refresh(self) -> None:
        from core.collaboration import list_workspaces
        self.ws_list.clear()
        for ws in list_workspaces():
            self.ws_list.addItem(
                f"{ws['name']}  [owner:{ws['owner_id']}]  {ws['status']}")
        self._current_ws = None
        self.comments_view.clear()
        self.versions_label.setText("")

    def _select_ws(self, item) -> None:
        from core.collaboration import list_workspaces
        name = item.text().split("  [")[0]
        for ws in list_workspaces():
            if ws["name"] == name:
                self._current_ws = ws
                self._load_comments()
                self._load_versions()
                return

    def _load_comments(self) -> None:
        if not self._current_ws:
            return
        from core.collaboration import list_comments
        comments = list_comments(self._current_ws["id"], self.resource_edit.text())
        self.comments_view.setPlainText("\n".join(
            f"[{c['user_id']} {c['created_at'][:16]}] {c['content']}" for c in comments) or "（暂无评论）")

    def _load_versions(self) -> None:
        if not self._current_ws:
            return
        from core.collaboration import list_versions
        vs = list_versions(self._current_ws["id"], self.resource_edit.text())
        self.versions_label.setText(" | ".join(
            f"v{v['version_no']}({v['user_id']})" for v in vs) or "（暂无版本）")

    # ---------------- 操作 ----------------
    def _create_ws(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            return
        try:
            from core.collaboration import create_workspace
            create_workspace(name, "local")
            self.name_edit.clear()
            self.refresh()
        except ValueError as e:
            QMessageBox.warning(self, "创建失败", str(e))

    def _add_comment(self) -> None:
        if not self._current_ws:
            QMessageBox.information(self, "提示", "请先选择空间")
            return
        text = self.comment_edit.text().strip()
        if text:
            from core.collaboration import add_comment
            add_comment(self._current_ws["id"], self.resource_edit.text(), "local", text)
            self.comment_edit.clear()
            self._load_comments()

    def _commit_version(self) -> None:
        if not self._current_ws:
            QMessageBox.information(self, "提示", "请先选择空间")
            return
        content = self.ver_content.text().strip()
        if content:
            from core.collaboration import commit_version
            commit_version(self._current_ws["id"], self.resource_edit.text(),
                           content, "local")
            self.ver_content.clear()
            self._load_versions()

    def _rollback(self) -> None:
        if not self._current_ws:
            return
        vno, ok = QInputDialog.getInt(self, "回滚", "回滚到版本号：", 1, 1, 999)
        if ok:
            from core.collaboration import rollback_to
            try:
                rollback_to(self._current_ws["id"], self.resource_edit.text(), vno, "local")
                self._load_versions()
            except ValueError as e:
                QMessageBox.warning(self, "回滚失败", str(e))
