# -*- coding: utf-8 -*-
"""机器可执行合规规则引擎。

将合规规则（禁用词 / 投资限制 / 风险阈值）编码为可配置 JSON/YAML 规则，
企业客户可自定义，无需改代码：
  - banned_word: 命中禁用词即违规（可配置白名单豁免）；
  - investment_limit: 仓位/金额上限（对上下文数值校验）；
  - risk_threshold: 风险指标阈值（如波动率、回撤）。

用法：
  rules = RuleEngine.load_json("data/compliance_rules.json")
  violations = engine.check({"text": "...", "position": ..., "risk": ...})
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger("stockai.compliance.rules")

_DEFAULT_RULES = {
    "banned_words": [
        "稳赚", "必涨", "翻倍", "内幕", "保本", "无风险", "涨停板敢死队",
        "加杠杆稳赢", "跟着买", "保证收益",
    ],
    "investment_limits": [
        {"field": "position", "max": 0.2, "label": "单一仓位上限 20%"},
        {"field": "leverage", "max": 1.0, "label": "杠杆上限 1x"},
    ],
    "risk_thresholds": [
        {"field": "volatility", "max": 0.05, "label": "日波动率上限 5%"},
        {"field": "drawdown", "max": 0.30, "label": "回撤上限 30%"},
    ],
    "whitelist": ["历史回测", "示例", "演示"],
}


class RuleEngine:
    """可配置合规规则引擎（线程安全）。"""

    def __init__(self, rules: dict | None = None):
        self._lock = threading.Lock()
        self._rules = dict(_DEFAULT_RULES)
        if rules:
            self._rules.update(rules)
        self._compiled = [re.compile(w) for w in self._rules.get("banned_words", [])]

    # ---------- 配置加载 ----------
    @classmethod
    def load_json(cls, path: str | Path) -> "RuleEngine":
        p = Path(path)
        if not p.exists():
            log.warning("规则文件不存在 %s，使用内置默认规则", p)
            return cls()
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def save_json(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._rules, f, ensure_ascii=False, indent=2)

    def add_rule(self, category: str, rule) -> None:
        with self._lock:
            self._rules.setdefault(category, []).append(rule)
            if category == "banned_words":
                self._compiled = [re.compile(w) for w in self._rules["banned_words"]]

    # ---------- 检查 ----------
    def check(self, context: dict) -> list[dict]:
        """对 {text, position, leverage, volatility, drawdown, ...} 上下文执行全部规则。"""
        violations: list[dict] = []
        text = str(context.get("text") or "")
        whitelist = self._rules.get("whitelist", [])

        # 1) 禁用词
        for w, pat in zip(self._rules.get("banned_words", []), self._compiled):
            if pat.search(text):
                if any(wl and wl in text for wl in whitelist):
                    continue
                violations.append({"rule": "banned_word", "detail": w,
                                   "level": "block"})
        # 2) 投资限制
        for lim in self._rules.get("investment_limits", []):
            val = context.get(lim["field"])
            if val is None:
                continue
            try:
                if float(val) > float(lim["max"]):
                    violations.append({"rule": "investment_limit",
                                       "detail": lim["label"],
                                       "field": lim["field"],
                                       "value": val, "max": lim["max"],
                                       "level": "warn"})
            except (TypeError, ValueError):
                continue
        # 3) 风险阈值
        for rt in self._rules.get("risk_thresholds", []):
            val = context.get(rt["field"])
            if val is None:
                continue
            try:
                if abs(float(val)) > float(rt["max"]):
                    violations.append({"rule": "risk_threshold",
                                       "detail": rt["label"],
                                       "field": rt["field"],
                                       "value": val, "max": rt["max"],
                                       "level": "warn"})
            except (TypeError, ValueError):
                continue
        return violations

    def is_blocked(self, violations: list[dict]) -> bool:
        return any(v["level"] == "block" for v in violations)

    def rules_summary(self) -> dict:
        return {k: len(v) for k, v in self._rules.items() if isinstance(v, list)}


if __name__ == "__main__":
    eng = RuleEngine()
    bad = eng.check({"text": "这只股票必涨，稳赚不赔", "position": 0.5, "leverage": 2.0})
    assert eng.is_blocked(bad), bad
    good = eng.check({"text": "历史回测显示波动率适中", "position": 0.1, "volatility": 0.02})
    assert not eng.is_blocked(good)
    # 自定义规则
    eng2 = RuleEngine()
    eng2.add_rule("banned_words", "包赢")
    assert eng2.check({"text": "包赢策略"})[0]["rule"] == "banned_word"
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)                       # 立即释放句柄，避免 Windows 文件锁
    eng2.save_json(tmp)
    eng3 = RuleEngine.load_json(tmp)
    assert eng3.check({"text": "包赢"})
    os.unlink(tmp)
    print(f"PASS rule_engine 自测 {eng.rules_summary()}")
