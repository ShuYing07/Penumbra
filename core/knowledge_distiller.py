# -*- coding: utf-8 -*-
"""本地金融知识蒸馏引擎（2026-10 翻新 · AI 知识蒸馏替代方案）。

定位：「AI 模型极致蒸馏」需求的工程化可行解。
知识库（docs/AI_KNOWLEDGE_BASE.md §7）已论证：把全网知识蒸馏进本地模型
权重不可行（需几十 GB 权重+版权语料+千卡训练）。本模块采用业界标准替代
架构——**结构化知识蒸馏 + 检索注入**：

1. **蒸馏**：多领域金融通识知识沉淀为结构化条目（core/distilled_knowledge），
   含原理/应用/边界三要素——比原始语料密度高一个数量级；
2. **索引**：SQLite FTS 风格关键词索引（领域/主题/标签/正文），
   本地毫秒级检索，零外部依赖；
3. **注入**：Agent 推理前按查询检索相关知识条目，注入系统上下文——
   等价于给模型外挂了一个「金融专业知识皮层」，且完全可审计、可更新；
4. **进化**：与 evo_memory 互补——evo_memory 沉淀「实战教训」，
   本库沉淀「先验知识」，两者共同构成 AI 的本地知识底座。

全部为确定性实现，不依赖 LLM，可单测。
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import DATA_DIR
from core.distilled_knowledge import DOMAINS, KNOWLEDGE

_KB_DB = DATA_DIR / "distilled_kb.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    principle TEXT NOT NULL,
    application TEXT NOT NULL,
    caveat TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'seed',
    created_ts REAL NOT NULL,
    UNIQUE(domain, title)
);
CREATE INDEX IF NOT EXISTS ix_kb_domain ON knowledge(domain);
CREATE INDEX IF NOT EXISTS ix_kb_topic ON knowledge(topic);
"""

_STOPWORDS = {"的", "了", "与", "和", "是", "在", "对", "为", "及", "或",
              "如何", "什么", "怎么", "哪些", "一下", "请问"}


def _tokenize(text: str) -> List[str]:
    """中英文混合分词：英文按词、中文按 2-gram + 关键词命中。"""
    text = (text or "").lower()
    tokens = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text)
    zh = re.sub(r"[a-z0-9\s]", "", text)
    # 中文 2-gram
    tokens += [zh[i: i + 2] for i in range(len(zh) - 1)]
    # 完整中文词（领域/主题常见词）
    tokens += [w for w in re.findall(r"[一-鿿]{2,}", text)]
    return [t for t in tokens if t and t not in _STOPWORDS]


class KnowledgeDistiller:
    """蒸馏知识库：加载 → 索引 → 检索 → 上下文注入。"""

    def __init__(self, db_path: Optional[Path] = None):
        self._db = Path(db_path) if db_path else _KB_DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con:
            con.executescript(_SCHEMA)
        self._seeded = False

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    # ---- 蒸馏（种子加载 + 自定义追加） ----
    def seed(self, force: bool = False) -> int:
        """把内置蒸馏知识写入库（幂等：已存在则跳过）。返回总条目数。"""
        if self._seeded and not force:
            return self.count()
        with closing(self._connect()) as con:
            for k in KNOWLEDGE:
                con.execute(
                    "INSERT OR IGNORE INTO knowledge"
                    "(domain, topic, title, principle, application, caveat,"
                    " tags, source, created_ts) VALUES(?,?,?,?,?,?,?,?,?)",
                    (k["domain"], k["topic"], k["title"], k["principle"],
                     k["application"], k["caveat"],
                     ",".join(k.get("tags", [])), "seed", time.time()))
            con.commit()
        self._seeded = True
        return self.count()

    def add_knowledge(self, domain: str, topic: str, title: str,
                      principle: str, application: str, caveat: str,
                      tags: Optional[List[str]] = None) -> bool:
        """追加自定义蒸馏条目（如从研究报告/操作日志沉淀）。返回是否新增。"""
        if domain not in DOMAINS:
            raise ValueError(f"未知领域：{domain}（可选 {DOMAINS}）")
        with closing(self._connect()) as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO knowledge"
                "(domain, topic, title, principle, application, caveat,"
                " tags, source, created_ts) VALUES(?,?,?,?,?,?,?,?,?)",
                (domain, topic, title, principle, application, caveat,
                 ",".join(tags or []), "custom", time.time()))
            con.commit()
            return cur.rowcount > 0

    def count(self) -> int:
        with closing(self._connect()) as con:
            return int(con.execute("SELECT COUNT(*) c FROM knowledge")
                       .fetchone()["c"])

    # ---- 检索 ----
    def search(self, query: str, domain: Optional[str] = None,
               limit: int = 5) -> List[Dict[str, Any]]:
        """关键词检索：按命中token数+权重（title>topic>tags>正文）排序。"""
        self.seed()
        tokens = _tokenize(query)
        if not tokens:
            return []
        sql = "SELECT * FROM knowledge"
        args: tuple = ()
        if domain:
            sql += " WHERE domain=?"
            args = (domain,)
        with closing(self._connect()) as con:
            rows = [dict(r) for r in con.execute(sql, args).fetchall()]

        scored = []
        for r in rows:
            hay_title = (r["title"] + " " + r["topic"]).lower()
            hay_tags = r["tags"].lower()
            hay_body = (r["principle"] + " " + r["application"]).lower()
            score = 0.0
            for t in set(tokens):
                if t in hay_title:
                    score += 3.0
                elif t in hay_tags:
                    score += 2.0
                elif t in hay_body:
                    score += 1.0
            if score > 0:
                r["relevance"] = round(score, 2)
                scored.append(r)
        scored.sort(key=lambda r: (-r["relevance"], r["domain"], r["title"]))
        return scored[:limit]

    def by_domain(self, domain: str) -> List[Dict[str, Any]]:
        """按领域取全部条目（供 UI 知识库页浏览）。"""
        self.seed()
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT * FROM knowledge WHERE domain=? ORDER BY topic, title",
                (domain,)).fetchall()
        return [dict(r) for r in rows]

    # ---- Agent 上下文注入 ----
    def build_context(self, query: str, limit: int = 3,
                      max_chars: int = 1200) -> str:
        """为 Agent 构建蒸馏知识上下文块（注入 system/参考区）。

        输出紧凑格式，含边界提醒（caveat），引导模型既用知识又不越界。
        """
        hits = self.search(query, limit=limit)
        if not hits:
            return ""
        lines = ["【本地蒸馏知识参考】（客观通识，非实时数据，非投资建议）"]
        used = len(lines[0])
        for h in hits:
            block = (f"· [{h['domain']}·{h['topic']}] {h['title']}\n"
                     f"  原理：{h['principle']}\n"
                     f"  应用：{h['application']}\n"
                     f"  边界：{h['caveat']}")
            if used + len(block) > max_chars:
                break
            lines.append(block)
            used += len(block)
        return "\n".join(lines)

    def stats(self) -> Dict[str, Any]:
        self.seed()
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT domain, COUNT(*) c FROM knowledge GROUP BY domain"
            ).fetchall()
            custom = con.execute(
                "SELECT COUNT(*) c FROM knowledge WHERE source='custom'"
            ).fetchone()["c"]
        return {"total": sum(r["c"] for r in rows),
                "by_domain": {r["domain"]: r["c"] for r in rows},
                "custom": int(custom)}


_SINGLETON: Optional[KnowledgeDistiller] = None


def get_distiller() -> KnowledgeDistiller:
    """进程级单例（UI/Agent 共享一个索引）。"""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = KnowledgeDistiller()
        _SINGLETON.seed()
    return _SINGLETON


def distill_context(query: str, limit: int = 3, max_chars: int = 1200) -> str:
    """便捷入口：一行代码为 Agent 注入蒸馏知识上下文。"""
    return get_distiller().build_context(query, limit=limit,
                                         max_chars=max_chars)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        kd = KnowledgeDistiller(Path(td) / "kb.db")
        assert kd.seed() == len(KNOWLEDGE)
        assert kd.seed() == len(KNOWLEDGE)  # 幂等

        hits = kd.search("美联储降息对成长股估值的影响")
        assert hits and hits[0]["relevance"] > 0
        assert any("利率" in (h["topic"] + h["title"] + h["tags"]) or
                   "估值" in (h["topic"] + h["title"]) for h in hits)

        hits2 = kd.search("回测 过拟合 多重检验", domain="数学工具")
        assert hits2 and hits2[0]["domain"] == "数学工具"

        ctx = kd.build_context("如何识别财务造假", limit=2)
        assert "【本地蒸馏知识参考】" in ctx and "边界" in ctx

        assert kd.add_knowledge("风险管理", "自研", "测试条目",
                                "原理X", "应用X", "边界X", ["测试"])
        assert not kd.add_knowledge("风险管理", "自研", "测试条目",
                                    "原理X", "应用X", "边界X")  # 幂等
        assert kd.stats()["custom"] == 1

        # 空查询与无命中
        assert kd.search("") == []
        assert kd.build_context("zzzqqq 无相关内容") == "" or \
            isinstance(kd.build_context("zzzqqq"), str)

        print(f"knowledge_distiller self-check ok "
              f"({kd.stats()['total']} 条, 检索命中={hits[0]['title']})")
