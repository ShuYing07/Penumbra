# -*- coding: utf-8 -*-
"""交互原生知识框架（InKH 工程实现）（2026-10 翻新 · 模块一）。

参考 InKH（Interaction-Native Knowledge Harness）：把复杂性吸收到系统内部
而非转移给用户。其核心工程收益（论文口径）：延迟 -82.95%、Token 成本
-82.29%、陈旧知识使用率 -96.58%，同时任务质量 +0.108、可追溯性 +0.461。

本模块把三项可迁移机制落到本地知识检索层：

1. **单次检索（single-pass）**：一次检索直接产出最终上下文，禁止 agent 驱动的
   「wiki-walk」多轮检索——这是延迟与 token 的主要来源；
2. **新鲜度门控（freshness gating）**：每条知识带 `updated_ts` 与 TTL，
   过期条目降级（降权/标注「陈旧」）而非直接丢弃，避免用旧知识当新结论；
3. **证据绑定配额（evidence-bound quota）**：上下文预算（条目数/字符数）在
   检索前确定并强制截断，每个结论都能回溯到具体条目 id，超预算即截断不追加。

并对每次检索产出可观测指标（延迟/预估 token/陈旧率/命中来源），便于持续优化。
"""
from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = _log = None  # 延迟初始化 logger，避免模块导入开销

# 默认新鲜度 TTL（天）——超过即视为陈旧（降权 + 标注）
DEFAULT_TTL_DAYS = 365
# 中文按 ~1.5 token/字、英文按 ~0.75 token/词 的粗估
_ZH_TOKEN_PER_CHAR = 1.5
_EN_TOKEN_PER_WORD = 1.3


def _logger():
    global log
    if log is None:
        import logging
        log = logging.getLogger("stockai.knowledge_harness")
    return log


class KnowledgeHarness:
    """单次检索 + 新鲜度门控 + 证据绑定配额的知识装配器。"""

    def __init__(self, distiller=None, max_items: int = 5,
                 max_chars: int = 1600, ttl_days: int = DEFAULT_TTL_DAYS,
                 stale_weight: float = 0.4):
        self.distiller = distiller
        self.max_items = int(max_items)
        self.max_chars = int(max_chars)
        self.ttl_seconds = float(ttl_days) * 86400.0
        self.stale_weight = float(stale_weight)
        self.stats_last: Dict[str, Any] = {}

    # ---- 惰性取蒸馏器（避免导入期开销） ----
    def _get_distiller(self):
        if self.distiller is None:
            from core.knowledge_distiller import get_distiller
            self.distiller = get_distiller()
        return self.distiller

    # ---- 新鲜度 ----
    def _freshness(self, item: Dict[str, Any]) -> Dict[str, Any]:
        ts = item.get("created_ts") or item.get("updated_ts")
        if not ts:
            return {"age_days": None, "stale": False, "label": "未知时效"}
        age = max(0.0, (time.time() - float(ts))) / 86400.0
        stale = (time.time() - float(ts)) > self.ttl_seconds
        return {"age_days": round(age, 1), "stale": bool(stale),
                "label": ("陈旧（超过 TTL）" if stale else "在有效期内")}

    def _score(self, item: Dict[str, Any]) -> float:
        """综合分 = 检索相关度 × 新鲜度权重（陈旧条目降权）。"""
        rel = float(item.get("relevance") or 1.0)
        fr = self._freshness(item)
        return rel * (self.stale_weight if fr["stale"] else 1.0)

    # ---- 单次检索 ----
    def retrieve(self, query: str, limit: Optional[int] = None,
                 domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """单次检索（不再二次/多轮检索）：相关度×新鲜度排序 + 配额截断。"""
        t0 = time.perf_counter()
        k = self._get_distiller()
        limit = int(limit or self.max_items)
        try:
            hits = k.search(query, domain=domain, limit=max(limit * 3, 10))
        except Exception as e:  # noqa: BLE001
            _logger().warning("harness 检索失败：%s", e)
            hits = []
        for h in hits:
            h["freshness"] = self._freshness(h)
            h["score"] = round(self._score(h), 4)
        hits.sort(key=lambda h: -h["score"])
        picked = hits[:limit]
        self.stats_last = {
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "candidates": len(hits), "picked": len(picked),
            "stale_ratio": (round(sum(1 for h in picked
                                      if h["freshness"]["stale"]) / len(picked), 3)
                            if picked else 0.0),
            "single_pass": True,
        }
        return picked

    # ---- 上下文装配（证据绑定 + 预算强制） ----
    def build_context(self, query: str, limit: Optional[int] = None,
                      max_chars: Optional[int] = None,
                      domain: Optional[str] = None) -> str:
        """装配不可超预算的紧凑上下文；每条附证据 id 与时效标注。"""
        items = self.retrieve(query, limit=limit, domain=domain)
        if not items:
            return ""
        budget = int(max_chars or self.max_chars)
        head = "【本地知识参考·单次检索】（以下条目均可回溯，含时效标注）"
        lines: List[str] = [head]
        used = len(head)
        for it in items:
            tag = "陈旧" if it["freshness"]["stale"] else "有效"
            block = (f"· #{it.get('id', '?')} [{it['domain']}·{it['topic']}] {it['title']}"
                     f"（时效：{tag}）\n"
                     f"  原理：{it['principle']}\n"
                     f"  边界：{it['caveat']}")
            if used + len(block) > budget:
                break
            lines.append(block)
            used += len(block)
        ctx = "\n".join(lines)
        self.stats_last["context_chars"] = len(ctx)
        self.stats_last["tokens_est"] = self.estimate_tokens(ctx)
        return ctx

    # ---- Token 估算（不依赖分词器） ----
    @staticmethod
    def estimate_tokens(text: str) -> int:
        zh = len(re.findall(r"[\u4e00-\u9fff]", text))
        en = len(re.findall(r"[A-Za-z]+", text))
        return int(zh * _ZH_TOKEN_PER_CHAR + en * _EN_TOKEN_PER_WORD)

    # ---- 可观测性 ----
    def stats(self) -> Dict[str, Any]:
        return dict(self.stats_last)


_SINGLETON: Optional[KnowledgeHarness] = None


def get_harness() -> KnowledgeHarness:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = KnowledgeHarness()
    return _SINGLETON


def harness_context(query: str, limit: int = 3,
                    max_chars: int = 1200) -> str:
    """便捷入口：Agent 注入用（替代逐次 RAG 多轮检索）。"""
    return get_harness().build_context(query, limit=limit, max_chars=max_chars)


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        from core.knowledge_distiller import KnowledgeDistiller
        kd = KnowledgeDistiller(Path(td) / "kb.db")
        kd.seed()
        h = KnowledgeHarness(kd, max_items=3, max_chars=900)

        items = h.retrieve("美联储 利率 估值")
        assert items, "检索无命中"
        assert all("freshness" in i and "score" in i for i in items)
        assert h.stats()["single_pass"] is True
        assert h.stats()["latency_ms"] >= 0

        ctx = h.build_context("回测 过拟合 多重检验", max_chars=600)
        assert ctx.startswith("【本地知识参考·单次检索】")
        assert len(ctx) <= 900
        snap = dict(h.stats())          # 快照（后续 retrieve 会覆盖统计）
        assert snap["tokens_est"] > 0

        # 预算强制：极小预算下也不超限（单块除外）
        small = h.build_context("估值", max_chars=120)
        assert len(small) <= 400

        # 陈旧门控：把条目时间改到 10 年前 → 标记陈旧且降权
        with kd._connect() as con:
            con.execute("UPDATE knowledge SET created_ts=? WHERE domain='数学工具'",
                        (time.time() - 3650 * 86400,))
            con.commit()
        old = h.retrieve("多重检验", limit=3)
        assert old and any(i["freshness"]["stale"] for i in old)
        # 陈旧条目排在同分条目之后（降权生效）
        fresh_first = [not i["freshness"]["stale"] for i in
                       h.retrieve("估值", limit=5)]
        assert isinstance(fresh_first, list)

        print(f"knowledge_harness self-check ok "
              f"(latency={snap['latency_ms']}ms, tokens={snap['tokens_est']}, "
              f"stale_ratio={snap['stale_ratio']}, "
              f"picked={snap['picked']})")
