# -*- coding: utf-8 -*-
"""认证与 RBAC 服务（企业版模块二）。

全部基于 Python 标准库（hashlib / hmac / base64），无需 python-jose / passlib
即可真实运行与测试；升级到 PostgreSQL 时接口不变。

- 密码哈希 : PBKDF2-HMAC-SHA256（40万迭代，每用户随机盐）；
- Token    : JWT 风格 HS256 签名（标准库 hmac 实现，含过期时间）；
- RBAC     : admin / analyst / viewer 三角色，permission 校验函数。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("stockai.auth")

TOKEN_TTL = 3600 * 8          # 8 小时
_PBKDF2_ITER = 400_000
_SECRET = None                # 进程内随机，重启失效（生产用持久密钥）


def _secret() -> bytes:
    global _SECRET
    if _SECRET is None:
        _SECRET = secrets.token_bytes(32)
    return _SECRET


def _db() -> Path:
    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "auth.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _init() -> None:
    with sqlite3.connect(_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users(
                user_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'analyst',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            )""")


ROLE_PERMISSIONS = {
    "admin":   {"view", "analyze", "backtest", "export", "manage_tenants",
                "manage_users", "delete_data"},
    "analyst": {"view", "analyze", "backtest", "export"},
    "viewer":  {"view"},
}


def register_user(tenant_id: str, username: str, password: str,
                  role: str = "analyst") -> dict:
    """注册用户（属于指定租户）。"""
    _init()
    if role not in ROLE_PERMISSIONS:
        raise ValueError(f"非法角色: {role}")
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                                   _PBKDF2_ITER).hex()
    user_id = "u_" + secrets.token_hex(8)
    with sqlite3.connect(_db()) as conn:
        try:
            conn.execute(
                "INSERT INTO users(user_id, tenant_id, username, password_hash,"
                " salt, role, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (user_id, tenant_id, username, pwd_hash, salt, role, "active",
                 time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"用户名已存在: {username}")
    return {"user_id": user_id, "tenant_id": tenant_id, "username": username,
            "role": role}


def verify_password(username: str, password: str) -> dict | None:
    """校验登录，成功返回用户信息，失败返回 None。"""
    _init()
    with sqlite3.connect(_db()) as conn:
        row = conn.execute("SELECT user_id,tenant_id,username,password_hash,salt,role,status"
                           " FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        return None
    user_id, tenant_id, uname, pwd_hash, salt, role, status = row
    if status != "active":
        return None
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                               _PBKDF2_ITER).hex()
    if not hmac.compare_digest(calc, pwd_hash):
        return None
    return {"user_id": user_id, "tenant_id": tenant_id, "username": uname,
            "role": role}


# ---------------------------------------------------------------- JWT 风格令牌

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: str, tenant_id: str, role: str, ttl: int = TOKEN_TTL) -> str:
    """签发 HS256 JWT 风格令牌。"""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub": user_id, "tenant": tenant_id, "role": role,
        "iat": int(time.time()), "exp": int(time.time()) + ttl,
    }).encode())
    sig = _b64url(hmac.new(_secret(), f"{header}.{payload}".encode(),
                           hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def verify_token(token: str) -> dict:
    """验证令牌，返回 payload；非法/过期抛 PermissionError。"""
    try:
        header, payload, sig = token.split(".")
        expect = _b64url(hmac.new(_secret(), f"{header}.{payload}".encode(),
                                  hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            raise PermissionError("令牌签名无效")
        data = json.loads(_unb64url(payload))
        if int(data["exp"]) < int(time.time()):
            raise PermissionError("令牌已过期")
        return data
    except PermissionError:
        raise
    except Exception as e:  # noqa: BLE001
        raise PermissionError(f"令牌解析失败: {e}")


def reset_password(username: str, new_password: str) -> bool:
    """密码重置（需调用方保证已认证）。"""
    _init()
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", new_password.encode(), salt.encode(),
                                   _PBKDF2_ITER).hex()
    with sqlite3.connect(_db()) as conn:
        cur = conn.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?",
                           (pwd_hash, salt, username))
        return cur.rowcount > 0


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def require(role: str, permission: str) -> None:
    """权限校验（不满足抛 PermissionError）。"""
    if not has_permission(role, permission):
        raise PermissionError(f"角色 {role} 无权限: {permission}")
