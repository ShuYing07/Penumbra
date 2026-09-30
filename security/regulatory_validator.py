# -*- coding: utf-8 -*-
"""监管验证器（模块六 · 参考 kbot-finance「规则即代码，管辖区感知」）。

把合规规则写成可检查的代码：每条规则 = {rule_id, jurisdiction, category,
severity, check(record) → (passed, message)}。支持多管辖区
（CN / US / EU / UK / SG / HK / GLOBAL），对 AI 工具调用记录 / 简报内容 /
推送行为做合规检查。与 compliance_sandbox（沙箱场景）互补：
本模块负责「规则库 + 判定」，沙箱负责「场景执行 + 状态写库」。

- RULES：内置规则库（可疑交易拆分、重大信息提前披露、超比例持仓、
  客户适当性、敏感词、业绩预告违规等）；
- validate_record(record, jurisdictions)：对一条记录跑指定辖区规则，
  返回 {rule_id, jurisdiction, severity, passed, message} 列表；
- report(records)：汇总为 {passed, total, failures, grade}。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("stockai.security.regulatory")


def _r_split(rec: dict) -> bool:
    """可疑交易拆分：同日内多笔接近阈值转账（模拟 Structuring 场景）。"""
    transfers = rec.get("transfers") or []
    threshold = float(rec.get("threshold", 10000))
    if not transfers:
        return True
    same_day = [t for t in transfers if t.get("day") == rec.get("day")]
    big = [t for t in same_day if float(t.get("amount", 0)) >= threshold * 0.95]
    if len(big) >= 2:
        return False
    return True


def _r_disclosure(rec: dict) -> bool:
    """重大信息：AI 输出不得提前泄露未公开重大信息。"""
    text = str(rec.get("content") or "")
    leaked = any(k in text for k in rec.get("unpublished", []))
    return not leaked


def _r_position(rec: dict) -> bool:
    """持仓比例：单一标的仓位不得超过上限（默认 20%）。"""
    pos = float(rec.get("position_pct", 0) or 0)
    limit = float(rec.get("position_limit", 0.20))
    return pos <= limit


def _r_suitability(rec: dict) -> bool:
    """客户适当性：高风险产品只向合格投资者推荐。"""
    product_risk = rec.get("product_risk", "low")
    investor = rec.get("investor_type", "retail")
    if product_risk == "high" and investor != "qualified":
        return False
    return True


def _r_sensitive(rec: dict) -> bool:
    """敏感表述：报告不得出现荐股/承诺收益类表述。"""
    text = str(rec.get("content") or "")
    bad = ["稳赚", "必涨", "保证收益", "无风险", "翻倍", "内幕消息"]
    return not any(b in text for b in bad)


def _r_forecast(rec: dict) -> bool:
    """业绩预告合规：不允许在未经披露的情况下预测精确业绩。"""
    text = str(rec.get("content") or "")
    if re.search(r"\d+\.\d+%", text) and "预告" not in str(rec.get("context") or ""):
        return "预计" not in text or "区间" in text
    return True


# rule_id: (jurisdiction, category, severity, check)
_RULES: Dict[str, tuple[str, str, str, Callable[[dict], bool]]] = {
    "structuring_split": ("GLOBAL", "反洗钱", "critical", _r_split),
    "material_disclosure": ("GLOBAL", "信息披露", "critical", _r_disclosure),
    "position_limit": ("CN", "持仓合规", "high", _r_position),
    "suitability": ("EU", "适当性", "high", _r_suitability),
    "sensitive_words": ("CN", "内容合规", "high", _r_sensitive),
    "forecast_rule": ("US", "披露合规", "medium", _r_forecast),
}

_JURISDICTION_RULES: Dict[str, List[str]] = {
    "GLOBAL": ["structuring_split", "material_disclosure"],
    "CN": ["position_limit", "sensitive_words", "structuring_split",
           "material_disclosure"],
    "US": ["forecast_rule", "material_disclosure", "sensitive_words"],
    "EU": ["suitability", "material_disclosure"],
    "UK": ["suitability", "material_disclosure"],
    "SG": ["structuring_split", "material_disclosure"],
    "HK": ["position_limit", "structuring_split"],
}


def rules_for(jurisdictions: Optional[List[str]] = None) -> List[str]:
    """返回指定辖区（缺省 GLOBAL）的规则 id 列表（去重、保序）。"""
    js = jurisdictions or ["GLOBAL"]
    out: List[str] = []
    for j in js:
        for rid in _JURISDICTION_RULES.get(j, _JURISDICTION_RULES["GLOBAL"]):
            if rid not in out:
                out.append(rid)
    return out


def validate_record(record: dict,
                    jurisdictions: Optional[List[str]] = None) -> List[dict]:
    """对一条记录跑指定辖区规则。返回逐规则结果。"""
    results: List[dict] = []
    for rid in rules_for(jurisdictions):
        j, cat, sev, check = _RULES[rid]
        try:
            passed = bool(check(record))
            msg = "通过" if passed else "违规：触发监管规则"
        except Exception as e:  # noqa: BLE001
            passed, msg = False, f"规则执行异常：{e}"
        results.append({"rule_id": rid, "jurisdiction": j, "category": cat,
                        "severity": sev, "passed": passed, "message": msg})
    return results


def compliance_report(records: List[dict],
                      jurisdictions: Optional[List[str]] = None) -> dict:
    """汇总审计记录合规状态。返回 {passed, total, failures, grade}。"""
    all_res: List[dict] = []
    for rec in records:
        all_res.extend(validate_record(rec, jurisdictions))
    total = len(all_res)
    failures = [r for r in all_res if not r["passed"]]
    critical = [r for r in failures if r["severity"] == "critical"]
    passed = not failures
    grade = "A" if not failures else \
        ("C" if critical else "B")
    return {"passed": passed, "total": total, "failures": failures,
            "critical_count": len(critical), "grade": grade,
            "summary": f"合规检查 {total} 项：通过 {total - len(failures)}，"
                       f"违规 {len(failures)}（致命 {len(critical)}）→ {grade} 级"}


if __name__ == "__main__":
    # 自检
    assert _r_split({"transfers": [{"day": "1", "amount": 9500},
                                   {"day": "1", "amount": 9500}],
                     "threshold": 10000, "day": "1"}) is False   # Structuring
    assert _r_split({"transfers": [{"day": "1", "amount": 8000}],
                     "threshold": 10000, "day": "1"}) is True
    assert _r_position({"position_pct": 0.25}) is False
    assert _r_position({"position_pct": 0.15}) is True
    assert _r_sensitive({"content": "这只票稳赚"}) is False
    assert _r_sensitive({"content": "注意风险"}) is True
    rec = {"content": "看好长期", "position_pct": 0.3, "transfers": [],
           "threshold": 10000, "day": "1", "unpublished": ["重组预案"]}
    res = validate_record(rec, ["CN"])
    assert any(not r["passed"] for r in res)   # 超仓违规
    rpt = compliance_report([rec, {"content": "正常公告", "position_pct": 0.1}],
                            ["CN"])
    assert rpt["grade"] == "B" and rpt["critical_count"] == 0
    print("regulatory_validator self-check ok")
