# -*- coding: utf-8 -*-
"""Agent Mesh：零信任 Agent 身份（HMAC-SHA256 令牌，标准库实现）。

令牌结构 header.payload.signature，与 JWT 同构；签名密钥来自 .env
AGENT_MESH_SECRET（未配置时取本机稳定随机值并持久化到 data/agent_mesh_secret.key）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from core.config import DATA_DIR

_SECRET_FILE = DATA_DIR / "agent_mesh_secret.key"
_TTL = 3600  # 令牌有效期 1 小时


def _secret() -> bytes:
    env = os.environ.get("AGENT_MESH_SECRET")
    if env:
        return env.encode("utf-8")
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_bytes()
    key = hashlib.sha256(os.urandom(32)).digest()
    _SECRET_FILE.write_bytes(key)
    return key


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(header_b64: str, payload_b64: str) -> str:
    msg = f"{header_b64}.{payload_b64}".encode("utf-8")
    return _b64(hmac.new(_secret(), msg, hashlib.sha256).digest())


def issue_identity(agent_id: str, name: str, ttl: int = _TTL) -> str:
    """为 Agent 签发身份令牌。"""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    now = int(time.time())
    payload = _b64(json.dumps({
        "sub": agent_id, "name": name, "iat": now, "exp": now + ttl,
    }).encode("utf-8"))
    return f"{header}.{payload}.{_sign(header, payload)}"


def verify_identity(token: str) -> dict:
    """验证令牌；失败抛 PermissionError。"""
    try:
        header_b64, payload_b64, sig = token.split(".")
    except ValueError:
        raise PermissionError("令牌格式错误") from None
    expect = _sign(header_b64, payload_b64)
    if not hmac.compare_digest(expect, sig):
        raise PermissionError("令牌签名无效")
    try:
        payload = json.loads(_unb64(payload_b64))
    except Exception:  # noqa: BLE001
        raise PermissionError("令牌载荷损坏") from None
    if int(payload.get("exp", 0)) < int(time.time()):
        raise PermissionError("令牌已过期")
    return payload
