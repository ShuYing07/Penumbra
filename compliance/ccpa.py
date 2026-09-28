# -*- coding: utf-8 -*-
"""CCPA 合规封装：知情权 + 不出售个人信息 + 删除权。

本程序不开设账号体系、不收集可识别个人信息、不出售任何数据；
此处提供声明与本地删除能力（面向加州用户界面展示用）。
"""
from __future__ import annotations

import json
from pathlib import Path

from core.config import DATA_DIR


def do_not_sell_declaration() -> str:
    """CCPA 不出售条款声明（固定展示文本）。"""
    return ("CCPA（加州消费者隐私法）：本程序不出售任何个人信息。"
            "本程序为本地优先工具，不设账号、不采集、不出售、不分享个人信息。"
            "用户数据仅存于本机 SQLite，可随时导出或删除。")


def set_do_not_sell(choice: bool = True) -> Path:
    """记录用户"不出售"偏好（本地持久化）。"""
    p = DATA_DIR / "ccpa_do_not_sell.json"
    p.write_text(json.dumps({"do_not_sell": choice, "version": "1.0"},
                            ensure_ascii=False), encoding="utf-8")
    return p


def get_do_not_sell() -> bool:
    p = DATA_DIR / "ccpa_do_not_sell.json"
    if not p.exists():
        return True  # 默认不出售
    try:
        return bool(json.loads(p.read_text(encoding="utf-8")).get("do_not_sell", True))
    except Exception:  # noqa: BLE001
        return True
