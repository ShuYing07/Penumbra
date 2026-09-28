# -*- coding: utf-8 -*-
"""不可篡改审计账本：SHA-256 哈希链（标准库实现，无需 cryptography）。

每条记录：{seq, ts, actor, action, detail, prev_hash, hash}
hash = sha256(seq|ts|actor|action|detail|prev_hash)
追加式写入；校验时从任意点重算哈希链，任何篡改都会断链。
"""
from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path

from core.config import DATA_DIR

_DB = DATA_DIR / "audit_ledger.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    prev_hash TEXT NOT NULL DEFAULT '',
    hash TEXT NOT NULL
);
"""


def _conn():
    import sqlite3
    from contextlib import closing, contextmanager

    @contextmanager
    def _open():
        con = sqlite3.connect(_DB)
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        with closing(con):
            yield con
            con.commit()

    return _open()

def _sha(msg: str) -> str:
    return hashlib.sha256(msg.encode("utf-8")).hexdigest()


def append(actor: str, action: str, detail: str = "") -> dict:
    """追加审计记录并返回该记录。"""
    with _conn() as c:
        last = c.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else "GENESIS"
        seq = (last["seq"] + 1) if last else 1
        ts = time.time()
        h = _sha(f"{seq}|{ts:.6f}|{actor}|{action}|{detail}|{prev}")
        c.execute(
            "INSERT INTO ledger(seq,ts,actor,action,detail,prev_hash,hash)"
            " VALUES(?,?,?,?,?,?,?)",
            (seq, ts, actor, action, detail, prev, h))
    return {"seq": seq, "ts": ts, "actor": actor, "action": action,
            "detail": detail, "prev_hash": prev, "hash": h}


def verify() -> tuple[bool, int]:
    """校验整条哈希链。返回 (是否完整, 记录条数)。"""
    with _conn() as c:
        rows = c.execute("SELECT * FROM ledger ORDER BY seq").fetchall()
    prev = "GENESIS"
    for r in rows:
        expect = _sha(f"{r['seq']}|{r['ts']:.6f}|{r['actor']}|{r['action']}|{r['detail']}|{prev}")
        if r["hash"] != expect or r["prev_hash"] != prev:
            return False, len(rows)
        prev = r["hash"]
    return True, len(rows)


def records(limit: int = 200) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM ledger ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def export_csv(path: str | Path | None = None) -> Path:
    """导出 CSV（UTF-8-SIG，Excel 可读）；返回路径。"""
    path = Path(path) if path else DATA_DIR / "audit_ledger_export.csv"
    rows = records(limit=10_000)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["seq", "ts", "actor", "action", "detail", "prev_hash", "hash"])
        for r in rows:
            w.writerow([r["seq"], r["ts"], r["actor"], r["action"],
                        r["detail"], r["prev_hash"], r["hash"]])
    return path


def export_json(path: str | Path | None = None) -> Path:
    path = Path(path) if path else DATA_DIR / "audit_ledger_export.json"
    path.write_text(json.dumps(records(limit=10_000), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path
