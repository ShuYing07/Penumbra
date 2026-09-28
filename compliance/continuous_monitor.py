# -*- coding: utf-8 -*-
"""持续合规监控 Agent。

从"分析完成后过滤"升级为"实时监测 AI 输出流"：
- monitor(text)：逐条执行规则引擎，命中风险信号立即入队；
- 人工审核队列：风险信号自动触发人工审核（review_queue），可认领/关闭；
- 审计：每次监测结果写入哈希链审计（security.audit_ledger）。

红线：block 级违规 → 输出被"拦截/替换"，绝不外发；
warn 级 → 标记并转人工。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from compliance.rule_engine import RuleEngine

log = logging.getLogger("stockai.compliance.monitor")


@dataclass
class ReviewItem:
    id: int
    ts: float
    ticker: str
    detail: str
    level: str          # block / warn
    status: str = "open"
    note: str = ""
    context: dict = field(default_factory=dict)


class ContinuousMonitor:
    """持续合规监控 Agent。"""

    def __init__(self, rule_engine: RuleEngine | None = None):
        self.rules = rule_engine or RuleEngine()
        self._lock = threading.Lock()
        self._seq = 0
        self.review_queue: list[ReviewItem] = []
        self.checked = 0
        self.blocked = 0
        self.warned = 0

    def monitor(self, text: str, ticker: str = "", context: dict | None = None) -> dict:
        """实时监测一段输出。

        返回 {checked, blocked, warned, blocked_total, warned_total, violations, sanitized}：
          - blocked: 本次是否触发 block 级拦截（bool）
          - warned:  本次 warn 级条数
          - blocked_total / warned_total: 累计计数（供面板展示）
        """
        ctx = dict(context or {})
        ctx["text"] = text
        with self._lock:
            self.checked += 1
        violations = self.rules.check(ctx)
        blocked = self.rules.is_blocked(violations)

        sanitized = text
        if blocked:
            # 拦截：违规文本不原样外发，替换为合规占位（避免在监控层拼接敏感词）
            sanitized = "[已触发合规拦截：该段内容不展示]"
        warned_now = 0
        for v in violations:
            level = v["level"]
            with self._lock:
                self._seq += 1
                item = ReviewItem(id=self._seq, ts=time.time(), ticker=ticker,
                                  detail=v.get("detail", ""), level=level,
                                  context=dict(ctx))
                self.review_queue.append(item)
                if level == "block":
                    self.blocked += 1
                else:
                    self.warned += 1
                    warned_now += 1
            self._audit(ticker, level, v.get("detail", ""))
        return {"checked": self.checked, "blocked": blocked, "warned": warned_now,
                "blocked_total": self.blocked, "warned_total": self.warned,
                "violations": violations, "sanitized": sanitized}

    # ---------- 人工审核 ----------
    def pending_reviews(self) -> list[dict]:
        with self._lock:
            return [{"id": i.id, "ts": i.ts, "ticker": i.ticker, "detail": i.detail,
                     "level": i.level, "status": i.status}
                    for i in self.review_queue if i.status == "open"]

    def review(self, item_id: int, approve: bool, note: str = "") -> bool:
        with self._lock:
            for i in self.review_queue:
                if i.id == item_id:
                    i.status = "approved" if approve else "closed"
                    i.note = note
                    return True
        return False

    def stats(self) -> dict:
        with self._lock:
            return {"checked": self.checked, "blocked": self.blocked,
                    "warned": self.warned, "pending": sum(
                        1 for i in self.review_queue if i.status == "open")}

    @staticmethod
    def _audit(ticker: str, level: str, detail: str) -> None:
        try:
            from security.audit_ledger import append as _aud
            _aud("compliance", f"monitor:{level}", f"ticker={ticker or '?'} {detail[:80]}")
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    m = ContinuousMonitor()
    r1 = m.monitor("这只股票必涨，稳赚不赔", ticker="SH600519")
    # 注意：sanitized 为「[已触发合规拦截：该段内容不展示]」，子串检查不含右括号
    assert r1["blocked"] is True and "[已触发合规拦截" in r1["sanitized"]
    r2 = m.monitor("历史回测显示该策略回撤可控", ticker="SH600519",
                   context={"position": 0.1})
    assert r2["blocked"] is False
    pending = m.pending_reviews()
    assert pending and pending[0]["level"] == "block"
    assert m.review(pending[0]["id"], approve=False, note="人工复核")
    assert m.stats()["checked"] == 2 and m.stats()["blocked"] == 2
    print(f"PASS continuous_monitor 自测 {m.stats()}")
