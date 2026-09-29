# -*- coding: utf-8 -*-
"""动态技能加载（参考 OpenBB Dynamic Skills）。

- 技能目录：skills/*.md，每个文件头部的 YAML 注释块声明
  slug / name / triggers（触发词）。
- Agent 按用户请求匹配技能：先看轻量级目录（slug+name+triggers），
  命中后按需加载完整 Markdown 指令注入 System Prompt，
  保持初始上下文精简、支持灵活扩展。
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

log = logging.getLogger("stockai.skill_loader")

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def _parse_frontmatter(text: str) -> Dict[str, str]:
    """解析文件头部 YAML 风格注释块：---\nkey: value\n---"""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta: Dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"\'')
    return meta


@lru_cache(maxsize=1)
def list_skills() -> List[Dict[str, str]]:
    """轻量技能目录：[{slug, name, triggers:[...]}]。"""
    out = []
    if not _SKILLS_DIR.exists():
        return out
    for f in sorted(_SKILLS_DIR.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        meta = _parse_frontmatter(text)
        slug = meta.get("slug") or f.stem
        raw_triggers = meta.get("triggers", "")
        # 支持 ["a", "b"] 与 a, b 两种写法
        triggers = re.findall(r"['\"]([^'\"]+)['\"]", raw_triggers)
        if not triggers:
            triggers = [t.strip() for t in raw_triggers.split(",") if t.strip()]
        out.append({"slug": slug, "name": meta.get("name", slug),
                    "triggers": triggers})
    return out


def load_skill(slug: str) -> str:
    """按需加载完整技能内容（Markdown 指令）。"""
    path = _SKILLS_DIR / f"{slug}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def match_skill(text: str) -> str:
    """按触发词匹配技能，返回 slug；无命中返回 ''。"""
    t = text or ""
    best, best_len = "", 0
    for s in list_skills():
        for trig in s["triggers"]:
            if trig and trig in t and len(trig) > best_len:
                best, best_len = s["slug"], len(trig)
    return best


def skills_prompt(text: str) -> str:
    """把命中技能的完整指令包装为 System 片段（未命中返回空）。"""
    slug = match_skill(text)
    if not slug:
        return ""
    body = load_skill(slug)
    if not body:
        return ""
    return (f"\n【当前激活技能：{slug}】\n请严格按以下技能指令执行：\n"
            f"{body}\n【技能指令结束】\n")
