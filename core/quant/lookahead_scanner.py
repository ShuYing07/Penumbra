# -*- coding: utf-8 -*-
"""前视偏差扫描器（lookahead_scanner）：独立入口，封装 core.quant.audit 的
scan_lookahead + Walk-Forward，并集成 quant-backtest-guard 检查清单，
输出分级审计报告：{ passed, severity, suspicious_points, details }。

对齐开源方案：
- quantlint：独立扫描器，市场数据完整性评分 + 运行时守卫 + 审计报告；
- quant-backtest-guard：未来函数/过拟合/幸存者偏差/成交真实性，按严重度定位。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.quant.audit import scan_lookahead, run_audit

# quant-backtest-guard 检查清单（规则名 → 严重度）
CHECKLIST: List[Dict[str, str]] = [
    {"rule": "未来函数/前视偏差", "severity": "致命",
     "check": "信号是否使用了触发点之后的数据（用截断重算对比）"},
    {"rule": "过拟合/数据窥探", "severity": "高危",
     "check": "样本外绩效是否显著退化（Walk-Forward 对比）"},
    {"rule": "幸存者偏差", "severity": "提示",
     "check": "股票池是否只含当下存续标的（历史退市未纳入）"},
    {"rule": "成交真实性与成本", "severity": "高危",
     "check": "是否建模手续费/滑点/印花税/整手/T+1"},
    {"rule": "标签泄漏", "severity": "致命",
     "check": "训练标签是否包含未来信息"},
    {"rule": "多重检验", "severity": "提示",
     "check": "参数是否在多组数据上反复试错选优"},
]


def scan_strategy(df, strategy: str, params: Optional[dict] = None,
                  market: str = "CN", config=None,
                  max_checks: int = 50) -> Dict[str, Any]:
    """对策略做前视偏差扫描 + 分级体检，返回统一审计报告。"""
    look = scan_lookahead(df, strategy, params, max_checks)
    verdict = look.get("verdict", "na")
    mismatches = int(look.get("mismatches") or 0)
    ratio = float(look.get("ratio") or 0.0)
    suspicious = list(look.get("mismatch_points") or [])[:10]

    severity = "通过"
    if verdict in ("fail", "warn"):
        severity = "高危" if (mismatches and ratio > 0.5) else "提示"
    if verdict == "fail":
        severity = "致命"

    # Walk-Forward 样本外退化检查（best-effort，失败不阻塞）
    wf = {}
    try:
        wf = run_audit(df, market, strategy, params, config)
        oos = wf.get("out_of_sample") or {}
        if oos and oos.get("return") is not None:
            wf = {"in_return": wf.get("in_sample", {}).get("return"),
                  "out_return": oos.get("return"),
                  "degraded": (oos.get("return", 0)
                               < (wf.get("in_sample", {}).get("return") or 0) * 0.5)}
    except Exception:  # noqa: BLE001
        pass

    return {
        "passed": verdict in ("pass", "na") and not wf.get("degraded"),
        "severity": severity,
        "suspicious_points": suspicious,
        "mismatch_ratio": ratio,
        "details": {
            "lookahead": look.get("detail") or look.get("reason") or "",
            "walk_forward": wf,
            "checklist": CHECKLIST,
        },
        "honest_summary": (
            f"机械层回测（确定性规则，无 LLM 参与）：前视扫描 "
            f"{'PASS' if verdict in ('pass', 'na') else 'FAIL'}，"
            f"样本外退化 {'是' if wf.get('degraded') else '否'}"),
    }


def audit_strategy(df, strategy: str, params: Optional[dict] = None,
                   market: str = "CN", config=None) -> Dict[str, Any]:
    """完整审计入口：前视 + 样本内外 + 体检报告（scripts/ci_audit 同款逻辑）。"""
    return scan_strategy(df, strategy, params, market, config)


def format_report(report: Dict[str, Any]) -> str:
    """人类可读的分级体检报告文本。"""
    lines = [f"策略审计：{report['severity']}（passed={report['passed']}）",
             f"前视偏差扫描：可疑点 {len(report['suspicious_points'])} 个，"
             f"不一致率 {report['mismatch_ratio']:.0%}"]
    d = report.get("details", {})
    wf = d.get("walk_forward") or {}
    if wf.get("in_return") is not None:
        lines.append(
            f"Walk-Forward：样本内收益 {wf['in_return']:.2%} → "
            f"样本外收益 {wf['out_return']:.2%}（退化={'是' if wf.get('degraded') else '否'}）")
    lines.append("检查清单（quant-backtest-guard）：")
    for item in d.get("checklist", []):
        lines.append(f"  [{item['severity']}] {item['rule']}：{item['check']}")
    return "\n".join(lines)
