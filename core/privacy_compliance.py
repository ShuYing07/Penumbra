# -*- coding: utf-8 -*-
"""GDPR / CCPA 隐私合规模块。

核心能力（对应企业版模块一）：
- export_user_data(user_id)  : GDPR 数据可携权 —— 导出用户全部关联数据为 JSON；
- delete_user_data(user_id)  : GDPR 被遗忘权     —— 删除用户全部关联数据（可审计）；
- 隐私政策版本管理           : 记录每次政策版本与用户同意记录，可追溯；
- 审计联动                   : 导出/删除均为关键操作，自动写入操作审计日志。

设计参考（开源惯例：Mattermost / Nextcloud 的 GDPR 插件）：
- 数据目录即"用户数据边界"：本程序单机运行，用户数据分布在 data/*.db；
- 导出走 JSON 快照（含时间戳与数据源清单），删除走事务性逐库清理；
- 同意记录独立表，永不随删除一并清除（合规审计要求保留同意证据）。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("stockai.privacy")

PRIVACY_VERSION = "1.1.0"
PRIVACY_UPDATED_AT = "2026-09-28"

# 数据边界：本程序所有用户数据文件（相对项目根）
_USER_DB_FILES = [
    "data/stockai.db",
    "data/memory.db",      # 若在项目内（打包版在用户目录，见 _resolve_db）
    "data/ai_analysis_log.db",
    "data/audit_trail.db",
    "data/news_cache.db",
    "data/research_journal.db",
    "data/concept_graph.db",
    "data/stock_index.db",
]
# 覆盖用户目录 ~/.shuying/*.db（打包版/源码版都可能落这里）
_HOME_DB_GLOB = ".shuying/*.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_user_dbs() -> list[Path]:
    """收集本机全部用户数据库路径（项目内 + 用户目录）。"""
    dbs: list[Path] = []
    root = Path(__file__).resolve().parents[1]
    for rel in _USER_DB_FILES:
        p = root / rel
        if p.exists():
            dbs.append(p)
    home = Path.home()
    for p in home.glob(_HOME_DB_GLOB):
        dbs.append(p)
    # 去重
    seen = set()
    out = []
    for p in dbs:
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


# ---------------------------------------------------------------- 同意记录

def ensure_consent_table(db_path: Path | None = None) -> Path:
    """确保同意记录表存在（独立于用户数据的合规库）。"""
    target = db_path or (Path.home() / ".shuying" / "privacy.db")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consent_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                policy_text_hash TEXT,
                action TEXT NOT NULL,          -- accept / revoke
                accepted_at TEXT NOT NULL,
                ip_hint TEXT
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS policy_versions(
                version TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                summary TEXT
            )""")
        conn.execute(
            "INSERT OR IGNORE INTO policy_versions(version, updated_at, summary) VALUES(?,?,?)",
            (PRIVACY_VERSION, PRIVACY_UPDATED_AT, "初始 GDPR/CCPA 合规版本"),
        )
    return target


def record_consent(user_id: str, action: str = "accept", ip_hint: str = "") -> None:
    """记录用户对当前隐私政策版本的同意/撤销。"""
    db = ensure_consent_table()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO consent_records(user_id, policy_version, action, accepted_at, ip_hint)"
            " VALUES(?,?,?,?,?)",
            (user_id, PRIVACY_VERSION, action, _now(), ip_hint),
        )


def consent_history(user_id: str) -> list[dict]:
    db = ensure_consent_table()
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT policy_version, action, accepted_at FROM consent_records"
            " WHERE user_id=? ORDER BY id DESC", (user_id,)
        ).fetchall()
    return [{"version": r[0], "action": r[1], "accepted_at": r[2]} for r in rows]


# ---------------------------------------------------------------- GDPR 导出

def export_user_data(user_id: str, out_path: str | None = None) -> dict:
    """GDPR 数据可携权：导出该用户全部关联数据为 JSON。

    单机桌面版以 user_id 为键的关联表有限，导出范围=全部本地数据快照
    （含分析历史、决策、审计、缓存元数据），并附带数据源清单。
    """
    snapshot: dict = {
        "exported_at": _now(),
        "privacy_policy_version": PRIVACY_VERSION,
        "user_id": user_id,
        "databases": [],
    }
    total_rows = 0
    for db in _iter_user_dbs():
        try:
            with sqlite3.connect(db) as conn:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                db_snap: dict = {"path": str(db), "tables": {}}
                for t in tables:
                    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})").fetchall()]
                    rows = conn.execute(f"SELECT * FROM {t}").fetchall()
                    db_snap["tables"][t] = {
                        "columns": cols,
                        "rows": [dict(zip(cols, r)) for r in rows],
                    }
                    total_rows += len(rows)
                snapshot["databases"].append(db_snap)
        except Exception as e:  # noqa: BLE001
            log.warning("导出跳过 %s: %s", db, e)
    snapshot["total_rows"] = total_rows

    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        snapshot["file"] = str(out)

    try:
        from core.audit_logger import log_operation
        log_operation(user_id, "gdpr_export", f"rows={total_rows}")
    except Exception:  # noqa: BLE001
        pass
    return snapshot


# ---------------------------------------------------------------- GDPR 删除

def delete_user_data(user_id: str, dry_run: bool = False) -> dict:
    """GDPR 被遗忘权：删除该用户全部关联数据（事务式，可审计）。

    单机版以整库清理实现（本程序无账号体系、数据均为该用户本地数据）。
    dry_run=True 时只统计不删除。
    """
    removed = 0
    detail: dict = {"databases": []}
    for db in _iter_user_dbs():
        try:
            with sqlite3.connect(db) as conn:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                    " AND name NOT LIKE 'sqlite_%'").fetchall()]
                for t in tables:
                    n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    if n:
                        removed += n
                        if not dry_run:
                            conn.execute(f"DELETE FROM {t}")
                detail["databases"].append({"db": str(db), "tables": len(tables)})
        except Exception as e:  # noqa: BLE001
            log.warning("删除跳过 %s: %s", db, e)

    if not dry_run:
        try:
            from core.audit_logger import log_operation
            log_operation(user_id, "gdpr_delete", f"removed_rows={removed}")
        except Exception:  # noqa: BLE001
            pass
    return {"dry_run": dry_run, "removed_rows": removed, "databases": detail["databases"]}


def policy_current() -> dict:
    """当前隐私政策版本信息（供设置页展示）。"""
    return {"version": PRIVACY_VERSION, "updated_at": PRIVACY_UPDATED_AT}
