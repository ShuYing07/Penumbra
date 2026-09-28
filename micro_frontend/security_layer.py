# -*- coding: utf-8 -*-
"""微前端统一安全合规层。

统一管理认证（token 校验）、授权（角色→权限）、审计（哈希链留痕）。
复用 security/zero_trust 与 security/audit_ledger 的既有实现，保持单一权威来源；
上层（主窗口/API）统一走本层，避免各模块各自为政。
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("stockai.micro_frontend.security")

_ROLE_PERMS = {
    "viewer": {"view"},
    "analyst": {"view", "analyze", "backtest", "export"},
    "admin": {"view", "analyze", "backtest", "export", "manage", "delete"},
}


class SecurityLayer:
    """统一安全合规层。"""

    def __init__(self, role: str = "analyst"):
        self.role = role if role in _ROLE_PERMS else "viewer"
        self._calls = 0
        self._denied = 0

    # ---------- 认证 ----------
    def authenticate(self, token: str | None) -> dict | None:
        """token 校验；空/无效返回 None。"""
        try:
            from security.zero_trust import authenticate as _zt_auth
            return _zt_auth(token)
        except Exception:  # noqa: BLE001
            return None

    # ---------- 授权 ----------
    def authorize(self, permission: str, **ctx) -> bool:
        self._calls += 1
        ok = permission in _ROLE_PERMS.get(self.role, set())
        # 上下文风控：异常时段的管理/删除操作拒绝
        hour = ctx.get("hour")
        if ok and permission in ("delete", "manage") and hour is not None:
            if hour >= 23 or hour < 6:
                ok = False
        if not ok:
            self._denied += 1
            self.audit("deny", f"permission={permission} role={self.role}")
        return ok

    # ---------- 审计 ----------
    def audit(self, action: str, detail: str = "") -> None:
        try:
            from security.audit_ledger import append as _aud
            _aud("microfrontend", action, detail)
        except Exception as e:  # noqa: BLE001
            log.warning("审计写入失败: %s", e)

    def stats(self) -> dict:
        return {"role": self.role, "calls": self._calls, "denied": self._denied}


if __name__ == "__main__":
    sl = SecurityLayer("analyst")
    assert sl.authorize("analyze", hour=10)
    assert not sl.authorize("delete", hour=10)
    assert not sl.authorize("manage", hour=23)
    assert sl.authorize("view", hour=10)
    assert sl.stats()["denied"] >= 2
    assert SecurityLayer("viewer").authorize("backtest", hour=10) is False
    print(f"PASS security_layer 自测 {sl.stats()}")
