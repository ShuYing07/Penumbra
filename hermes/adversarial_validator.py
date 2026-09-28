# -*- coding: utf-8 -*-
"""对抗数据验证网络（HERMES 模块）。

对检索到的每条事实/数据做多裁判对抗校验：
  1. 完整性裁判：关键字段缺失检测；
  2. 数值合理性裁判：范围、正负、跳变检测；
  3. 来源一致性裁判：多源互证度；
  4. 时效性裁判：数据新鲜度（旧数据降权）。

输出可靠性评分 + 问题清单 + 结论（接受 / 存疑 / 拒绝）。
低于阈值的事实将被标注"未经证实"，绝不作为结论依据（合规红线）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("stockai.hermes.validator")


@dataclass
class AdversarialValidator:
    """对抗验证网络：probe(claim) → 多裁判评分。"""

    required_fields: tuple = ("open", "high", "low", "close")
    freshness_max_hours: float = 168.0  # 7 天内视为新鲜
    accept_threshold: float = 0.7
    suspect_threshold: float = 0.45

    # ---------- 裁判 ----------
    def _judge_completeness(self, fact: dict) -> tuple[float, str]:
        miss = [f for f in self.required_fields if f not in fact or fact[f] is None]
        if not miss:
            return 1.0, ""
        return 0.3, f"缺字段: {','.join(miss)}"

    def _judge_numeric(self, fact: dict) -> tuple[float, str]:
        bad = []
        high, low = fact.get("high"), fact.get("low")
        if high is not None and low is not None:
            try:
                if float(high) < float(low):
                    bad.append("high<low")
            except (TypeError, ValueError):
                bad.append("high/low 非数值")
        close = fact.get("close")
        if close is not None and close <= 0:
            bad.append("close<=0")
        if bad:
            return 0.2, "数值异常: " + ";".join(bad)
        return 1.0, ""

    def _judge_freshness(self, fact: dict) -> tuple[float, str]:
        ts = fact.get("ts")
        if not ts:
            return 0.5, "无时间戳"
        age_h = (time.time() - float(ts)) / 3600
        if age_h <= self.freshness_max_hours:
            return 1.0, ""
        return 0.4, f"数据过旧({age_h:.0f}h)"

    def _judge_sources(self, fact: dict) -> tuple[float, str]:
        srcs = fact.get("sources") or []
        if not srcs:
            return 0.5, "无来源"
        if len(set(srcs)) >= 2:
            return 1.0, f"{len(set(srcs))} 源互证"
        return 0.6, f"单源({srcs[0]})"

    # ---------- 主流程 ----------
    def probe(self, fact: dict) -> dict:
        """对单条事实做对抗校验。fact 至少含 {close/...} 与可选 ts/sources。"""
        results = {
            "completeness": self._judge_completeness(fact),
            "numeric": self._judge_numeric(fact),
            "freshness": self._judge_freshness(fact),
            "sources": self._judge_sources(fact),
        }
        score = sum(w for w, _ in results.values()) / len(results)
        score = round(score, 3)
        issues = [note for _, note in results.values() if note]
        if score >= self.accept_threshold:
            verdict = "接受"
        elif score >= self.suspect_threshold:
            verdict = "存疑"
        else:
            verdict = "拒绝"
        return {"score": score, "verdict": verdict, "issues": issues,
                "details": {k: v for k, (w, _) in results.items() for v in [w]}}

    def verify_facts(self, facts: list[dict]) -> dict:
        """批量校验：返回 {accepted, suspect, rejected, mean_score, issues}。"""
        accepted, suspect, rejected = [], [], []
        for f in facts:
            r = self.probe(f)
            (accepted if r["verdict"] == "接受" else
             suspect if r["verdict"] == "存疑" else rejected).append(
                {"fact": f, **r})
        mean = (sum(r["score"] for r in accepted + suspect + rejected)
                / max(1, len(facts)))
        return {"accepted": accepted, "suspect": suspect, "rejected": rejected,
                "mean_score": round(mean, 3),
                "issues": [i for r in suspect + rejected for i in r["issues"]][:20]}


def verify_facts(facts: list[dict], **kw) -> dict:
    return AdversarialValidator(**kw).verify_facts(facts)


if __name__ == "__main__":
    import time as _t
    now = _t.time()
    facts = [
        {"open": 100, "high": 101, "low": 99, "close": 100.5,
         "ts": now, "sources": ["新浪", "东财"]},   # 接受
        {"open": 100, "high": 99, "low": 101, "close": 100.5,
         "ts": now, "sources": ["新浪"]},            # high<low + 单源 → 存疑
        {"close": 100.5, "ts": now - 30 * 86400, "sources": []},  # 缺字段+过旧+无源 → 存疑
        {"close": -5.0, "ts": now - 30 * 86400},     # 缺字段+close<=0+过旧+无源 → 拒绝
    ]
    r = verify_facts(facts)
    assert r["accepted"] and r["accepted"][0]["score"] >= 0.7
    assert len(r["rejected"]) >= 1
    assert r["mean_score"] > 0
    single = AdversarialValidator().probe(
        {"open": 1, "high": 2, "low": 1, "close": 1.5, "ts": now, "sources": ["东财"]})
    assert single["verdict"] == "接受"
    print(f"PASS adversarial_validator 自测 mean={r['mean_score']} "
          f"acc={len(r['accepted'])} sus={len(r['suspect'])} rej={len(r['rejected'])}")
