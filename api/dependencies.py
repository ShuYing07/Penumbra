# -*- coding: utf-8 -*-
"""REST API —— 认证依赖注入（企业版模块三）。

复用 core/auth_service 的标准库 JWT 实现；FastAPI 依赖项：
    def current_user(authorization: str = Header(...)) -> dict:
        return get_current_user(authorization, require_role="analyst")
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.auth_service import verify_token, require, ROLE_PERMISSIONS  # noqa: E402


def get_current_user(authorization: str, require_role: str | None = None) -> dict:
    """从 Authorization: Bearer <token> 解析并校验用户；可选角色校验。

    require_role 为角色等级（admin > analyst > viewer），映射到对应权限校验；
    返回 {"sub","tenant","role","exp"}；非法/无权限抛 PermissionError。
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise PermissionError("缺少 Bearer Token")
    token = authorization.split(" ", 1)[1].strip()
    payload = verify_token(token)
    if require_role:
        if require_role == "admin":
            require(payload["role"], "manage_tenants")
        elif require_role == "analyst":
            require(payload["role"], "analyze")
        elif require_role == "viewer":
            require(payload["role"], "view")
        else:
            require(payload["role"], require_role)
    return payload
