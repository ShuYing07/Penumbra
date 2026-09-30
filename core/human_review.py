# -*- coding: utf-8 -*-
"""人类审校节点（模块二 · 参考 invest-research-agent Human-in-the-loop）。

AI 报告生成后进入审校状态机：pending → approved / edited / rejected。
**未经审校（approved/edited）的内容不得写入知识库**——本模块提供
`review_gate` 守卫函数，`agent_core` 只有在审校通过时才调用 save_analysis。

设计：
- ReviewRecord：单份报告的状态记录（逐段采纳/修改/驳回的 JSON 结构）；
- ReviewGate：内存存储 + SQLite 持久化（reviews 表）；
- approve / edit / reject 操作 + can_commit(review_id) 守卫；
- UI 可直接用 approve_segment/edit_segment/reject_segment 逐段操作。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("stockai.core.human_review")

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "reviews.db")


class ReviewRecord:
    def __init__(self, review_id: str, content: str, meta: Optional[dict] = None):
        self.review_id = review_id
        self.content = content
        self.meta = meta or {}
        self.segments: List[Dict[str, str]] = []   # [{id, text, status}]
        self.status = "pending"                     # pending/approved/edited/rejected
        self.created_at = time.time()

    def split_segments(self) -> None:
        """把报告按段落拆成可逐段审校的片段。"""
        paras = [p.strip() for p in (self.content or "").split("\n")
                 if p.strip()]
        self.segments = [{"id": f"s{i}", "text": p, "status": "pending"}
                         for i, p in enumerate(paras)]
        if not self.segments:
            self.segments = [{"id": "s0", "text": self.content or "", "status": "pending"}]

    def approve_segment(self, seg_id: str) -> bool:
        for s in self.segments:
            if s["id"] == seg_id:
                s["status"] = "approved"
                return True
        return False

    def edit_segment(self, seg_id: str, new_text: str) -> bool:
        for s in self.segments:
            if s["id"] == seg_id:
                s["text"] = new_text
                s["status"] = "edited"
                return True
        return False

    def reject_segment(self, seg_id: str) -> bool:
        for s in self.segments:
            if s["id"] == seg_id:
                s["status"] = "rejected"
                return True
        return False

    def finalize(self) -> None:
        statuses = {s["status"] for s in self.segments}
        if not self.segments or statuses == {"approved"}:
            self.status = "approved"
        elif "rejected" in statuses and statuses <= {"approved", "edited", "rejected"}:
            self.status = "rejected" if all(s["status"] == "rejected"
                                            for s in self.segments) else "edited"
        else:
            self.status = "edited"

    def approved_text(self) -> str:
        """取审校后文本（rejected 段落剔除）。"""
        return "\n".join(s["text"] for s in self.segments
                         if s["status"] in ("approved", "edited"))

    def to_dict(self) -> dict:
        return {"review_id": self.review_id, "content": self.content,
                "meta": self.meta, "segments": self.segments,
                "status": self.status, "created_at": self.created_at}


class ReviewGate:
    """审校状态机 + SQLite 持久化。"""

    def __init__(self, db: str = _DB):
        self._lock = threading.Lock()
        self._records: Dict[str, ReviewRecord] = {}
        self._db = db
        os.makedirs(os.path.dirname(db), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.execute("CREATE TABLE IF NOT EXISTS reviews "
                  "(review_id TEXT PRIMARY KEY, payload TEXT, updated_at REAL)")
        return c

    def _init_db(self) -> None:
        try:
            c = self._conn()
            c.close()
        except Exception as e:  # noqa: BLE001
            log.warning("审校库初始化失败（降级内存）：%s", e)

    def create(self, content: str, meta: Optional[dict] = None) -> ReviewRecord:
        rec = ReviewRecord(uuid.uuid4().hex[:12], content, meta)
        rec.split_segments()
        with self._lock:
            self._records[rec.review_id] = rec
            self._persist(rec)
        return rec

    def get(self, review_id: str) -> Optional[ReviewRecord]:
        return self._records.get(review_id)

    def approve_segment(self, review_id: str, seg_id: str) -> Optional[dict]:
        rec = self.get(review_id)
        if not rec:
            return None
        ok = rec.approve_segment(seg_id)
        if ok:
            rec.finalize()
            self._persist(rec)
        return {"ok": ok, "status": rec.status}

    def edit_segment(self, review_id: str, seg_id: str, new_text: str) -> Optional[dict]:
        rec = self.get(review_id)
        if not rec:
            return None
        ok = rec.edit_segment(seg_id, new_text)
        if ok:
            rec.finalize()
            self._persist(rec)
        return {"ok": ok, "status": rec.status}

    def reject_segment(self, review_id: str, seg_id: str) -> Optional[dict]:
        rec = self.get(review_id)
        if not rec:
            return None
        ok = rec.reject_segment(seg_id)
        if ok:
            rec.finalize()
            self._persist(rec)
        return {"ok": ok, "status": rec.status}

    def approve_all(self, review_id: str) -> Optional[dict]:
        rec = self.get(review_id)
        if not rec:
            return None
        for s in rec.segments:
            s["status"] = "approved"
        rec.finalize()
        self._persist(rec)
        return {"ok": True, "status": rec.status}

    def can_commit(self, review_id: str) -> bool:
        """守卫：仅 approved/edited（有可用文本）可写入知识库。"""
        rec = self.get(review_id)
        if not rec or rec.status not in ("approved", "edited"):
            return False
        return bool(rec.approved_text().strip())

    def commit_payload(self, review_id: str) -> Optional[str]:
        """审校通过后取可写入知识库的文本。"""
        if not self.can_commit(review_id):
            return None
        return self.get(review_id).approved_text()

    def _persist(self, rec: ReviewRecord) -> None:
        try:
            c = self._conn()
            c.execute("INSERT OR REPLACE INTO reviews (review_id, payload, updated_at) "
                      "VALUES (?, ?, ?)",
                      (rec.review_id, json.dumps(rec.to_dict(), ensure_ascii=False),
                       time.time()))
            c.commit()
            c.close()
        except Exception as e:  # noqa: BLE001
            log.debug("审校持久化失败（内存模式继续）：%s", e)

    def list_recent(self, limit: int = 50) -> List[dict]:
        recs = sorted(self._records.values(), key=lambda r: r.created_at,
                      reverse=True)
        return [r.to_dict() for r in recs[:limit]]


def review_gate(can_commit: bool) -> bool:
    """便捷守卫函数：False 时禁止写知识库（用于断言式调用）。"""
    return can_commit


if __name__ == "__main__":
    gate = ReviewGate()
    rec = gate.create("第一段结论。\n第二段结论。\n", {"ticker": "600519"})
    assert rec.status == "pending"
    assert gate.can_commit(rec.review_id) is False       # 未审校禁止提交
    gate.approve_segment(rec.review_id, rec.segments[0]["id"])
    gate.reject_segment(rec.review_id, rec.segments[1]["id"])
    assert gate.can_commit(rec.review_id) is True        # 部分通过后可提交
    text = gate.commit_payload(rec.review_id)
    assert "第一段结论" in text and "第二段结论" not in text
    r2 = gate.create("只一段。", {})
    gate.reject_segment(r2.review_id, r2.segments[0]["id"])
    assert gate.can_commit(r2.review_id) is False        # 全部驳回禁止提交
    print("human_review self-check ok")
