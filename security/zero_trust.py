# -*- coding: utf-8 -*-
"""零信任安全：持续认证 + 上下文授权（标准库实现，无 pyjwt 依赖）。

- authenticate(token)：每次调用校验令牌（复用 core.auth_service JWT / agent_identity）；
- authorize(user, action, context)：按角色 + 时间 + 来源（IP/设备）动态裁决，
  无显式策略默认拒绝；
- 内置基于时段与来源的异常判定（非常规时段/未知来源降权）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class AuthContext:
    role: str = "viewer"
    ip: str = ""
    device: str = ""
    hour: int = 0            # 本地小时 0-23
    weekday: int = 0         # 0=周一
    risk_extra: float = 0.0  # 外部风险加分（0~1）


# 角色 → 允许的动作
_ROLE_ACTIONS = {
    "viewer": {"view"},
    "analyst": {"view", "run_analysis", "run_backtest", "export"},
    "admin": {"view", "run_analysis", "run_backtest", "export", "delete", "manage"},
}


def authenticate(token: str) -> dict:
    """持续认证：校验令牌，返回身份信息 {user_id, role, tenant_id}。"""
    from core.auth_service import verify_token
    return verify_token(token)  # 无效/过期抛 PermissionError


def authorize(user: dict, action: str, ctx: AuthContext | None = None) -> bool:
    """上下文授权：角色动作 + 时段 + 来源动态裁决。"""
    ctx = ctx or AuthContext()
    role = (user or {}).get("role", "viewer")
    if action not in _ROLE_ACTIONS.get(role, set()):
        return False

    # 异常时段（23:00-06:00）敏感动作需 admin（修复：原写法 or 优先级错误，
    # 导致凌晨时段所有动作均被误判拒绝）
    if action in ("delete", "manage") and (ctx.hour >= 23 or ctx.hour < 6):
        if role != "admin":
            return False
    # 未知来源（IP/设备缺失）敏感动作降权
    if action in ("export", "delete") and not (ctx.ip or ctx.device):
        return False
    # 外部风险加成：>0.5 时拒绝
    if ctx.risk_extra > 0.5:
        return False
    return True


def enforce(user: dict, action: str, ctx: AuthContext | None = None) -> None:
    if not authorize(user, action, ctx):
        raise PermissionError(
            f"零信任拒绝：role={user.get('role')} action={action} "
            f"hour={ctx.hour if ctx else '-'} risk={ctx.risk_extra if ctx else 0}")


def risk_score(ip: str, device: str) -> float:
    """来源风险分：0-1（IP 与设备均缺失视为高风险的内部信号）。"""
    score = 0.0
    if not ip:
        score += 0.5
    if not device:
        score += 0.3
    return min(score, 1.0)
