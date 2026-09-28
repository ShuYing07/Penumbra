# -*- coding: utf-8 -*-
"""GDPR 合规封装：数据可携权（导出）与被遗忘权（删除）。

复用 core.privacy_compliance 的事务性实现；此处提供面向业务的别名接口。
"""
from __future__ import annotations

from pathlib import Path

from core.privacy_compliance import (export_user_data as _export,
                                     delete_user_data as _delete)


def export_user_data(user_id: str, out_path: str | Path | None = None) -> dict:
    """GDPR Art.20 数据可携权：导出用户全部数据为 JSON 快照。"""
    return _export(user_id, out_path=out_path)


def delete_user_data(user_id: str, dry_run: bool = False) -> dict:
    """GDPR Art.17 被遗忘权：删除用户全部数据（事务性，可预演）。"""
    return _delete(user_id, dry_run=dry_run)


def data_subject_rights() -> dict:
    """告知数据主体权利（界面展示用）。"""
    return {
        "access": "访问权：查看本人全部数据（export_user_data）",
        "portability": "可携权：以 JSON 格式导出（Art.20）",
        "erasure": "删除权：删除全部本地数据（Art.17）",
        "rectification": "更正权：数据由用户在本机自行维护",
        "consent": "同意记录：版本化 consent 留痕（privacy_compliance）",
    }
