# -*- coding: utf-8 -*-
"""可选登录对话框（企业版）：本地认证，默认关闭。

启用方式：在 .env 或 QSettings 中设置 enterprise_login=1 后，
启动时要求用户名/密码（core/auth_service.py 校验）。
普通用户默认不受影响。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QDialog, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout, QHBoxLayout, QMessageBox)


def is_login_enabled() -> bool:
    """企业登录开关：QSettings enterprise_login 或环境变量 STOCKAI_LOGIN=1。"""
    import os
    if os.environ.get("STOCKAI_LOGIN") == "1":
        return True
    try:
        from PyQt6.QtCore import QSettings
        return bool(QSettings("StockAI", "StockAIPredictor").value(
            "enterprise_login", False, type=bool))
    except Exception:  # noqa: BLE001
        return False


def prompt_login(parent=None) -> dict | None:
    """弹出登录框；验证通过返回用户信息 dict，取消返回 None。"""
    from PyQt6.QtCore import QSettings
    from core.auth_service import verify_password

    dlg = QDialog(parent)
    dlg.setWindowTitle("疏影·知微 企业登录")
    dlg.setMinimumWidth(340)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel("企业版登录（本地认证）\n"
                         "用户名/密码由管理员配置（core/auth_service）"))
    u = QLineEdit(); u.setPlaceholderText("用户名")
    p = QLineEdit(); p.setPlaceholderText("密码"); p.setEchoMode(QLineEdit.EchoMode.Password)
    lay.addWidget(u); lay.addWidget(p)
    row = QHBoxLayout()
    ok = QPushButton("登录")
    ok.setStyleSheet("background:#00E5FF; color:#0A0E17; border-radius:6px; padding:6px 16px;")
    cancel = QPushButton("取消")
    row.addWidget(ok); row.addWidget(cancel)
    lay.addLayout(row)
    result: dict | None = None

    def _do():
        nonlocal result
        user = verify_password(u.text().strip(), p.text())
        if user is None:
            QMessageBox.warning(dlg, "登录失败", "用户名或密码错误")
            return
        result = user
        try:
            from core.audit_logger import log_operation
            log_operation(user["user_id"], "login", f"user={u.text().strip()}")
        except Exception:  # noqa: BLE001
            pass
        dlg.accept()

    ok.clicked.connect(_do)
    cancel.clicked.connect(dlg.reject)
    u.returnPressed.connect(_do)
    p.returnPressed.connect(_do)
    dlg.exec()
    return result
