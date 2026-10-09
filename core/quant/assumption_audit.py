# -*- coding: utf-8 -*-
"""九维回测假设审计（skill-backtest-assumption-check 思路落地）。

回测从来不是"跑一遍历史"那么简单——它建立在**一堆没说出口的假设**上：
能成交吗？按什么价成交？成本多少？滑点多少？股票池有没有幸存者偏差？
这些假设只要有一条与现实不符，漂亮的净值曲线就是幻觉。

本模块把九类假设逐条摊开检查，输出统一为
**缺陷 × 证据 × 严重度 × 影响 × 修复**：

1. 数据可用性   2. 成交假设   3. 流动性   4. 成本   5. 滑点
6. 幸存者偏差   7. 时间对齐   8. 市场冲击  9. 分红除权

设计：全部基于 df / 配置 / 参数可观测的事实判定，**不依赖 LLM、不需要网络**，
因此可单测、可复现、可进 CI 门禁。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

log = logging.getLogger("stockai.quant.assumption")

_SEV_ORDER = {"FATAL": 0, "WARN": 1, "INFO": 2, "OK": 3}

DIMENSIONS: List[Dict[str, str]] = [
    {"id": "data_availability", "name": "数据可用性",
     "question": "缺失/停牌/零成交的 bar 是如何处理的？"},
    {"id": "fill", "name": "成交假设",
     "question": "信号产生后以什么价格、什么时点成交？"},
    {"id": "liquidity", "name": "流动性",
     "question": "市场成交量能否容纳策略的仓位？"},
    {"id": "cost", "name": "成本",
     "question": "手续费/印花税/过户费是否已建模？"},
    {"id": "slippage", "name": "滑点",
     "question": "买卖价差与延迟导致的滑点是否已计入？"},
    {"id": "survivorship", "name": "幸存者偏差",
     "question": "股票池是否只含当下仍存续的标的？"},
    {"id": "time_alignment", "name": "时间对齐",
     "question": "时间戳口径与 T+1 结算是否正确？"},
    {"id": "market_impact", "name": "市场冲击",
     "question": "自身下单会不会推动价格？"},
    {"id": "dividend", "name": "分红除权",
     "question": "分红/送转/拆并股的除权除息是否已处理？"},
]


def _f(id_: str, severity: str, defect: str, evidence: str,
       impact: str, fix: str) -> Dict[str, Any]:
    return {"id": id_, "severity": severity, "defect": defect,
            "evidence": evidence, "impact": impact, "fix": fix}


def _num(d: Dict[str, Any], *keys, default: float = 0.0) -> float:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return default


def audit_assumptions(df: Optional[pd.DataFrame] = None,
                      market: str = "CN",
                      strategy: str = "ma_cross",
                      params: Optional[Dict[str, Any]] = None,
                      config: Any = None,
                      universe: Optional[List[str]] = None,
                      capital: float = 1_000_000.0,
                      position_pct: float = 100.0) -> Dict[str, Any]:
    """九维假设审计。返回 {dimensions, findings, counts, passed, summary}。"""
    params = dict(params or {})
    findings: List[Dict[str, Any]] = []

    # ---------- 1. 数据可用性 ----------
    if df is None or len(df) == 0:
        findings.append(_f("data_availability", "FATAL", "没有行情数据",
                           "df 为空", "无法做任何有效回测",
                           "先拉取并校验行情数据"))
    else:
        n = len(df)
        zero_vol = int((pd.to_numeric(df.get("volume"), errors="coerce").fillna(0) == 0).sum()) \
            if "volume" in df.columns else 0
        nan_close = int(pd.to_numeric(df.get("close"), errors="coerce").isna().sum()) \
            if "close" in df.columns else 0
        if nan_close:
            findings.append(_f("data_availability", "FATAL",
                               f"收盘价存在 {nan_close} 个缺失值",
                               f"close 列 NaN 占比 {nan_close / n:.1%}",
                               "缺失值会被填充或跳过，收益率序列失真",
                               "补齐数据或显式剔除，禁止用 bfill（未来值）"))
        if zero_vol:
            ratio = zero_vol / n
            findings.append(_f("data_availability",
                               "WARN" if ratio < 0.1 else "FATAL",
                               f"{zero_vol} 根零成交 bar（疑似停牌）",
                               f"volume=0 占比 {ratio:.1%}",
                               "停牌期间无法真实成交，若照常下单等于假设流动性恒在",
                               "停牌日禁止开仓/平仓，或标注为不可交易"))
        if not findings or all(f["id"] != "data_availability" for f in findings):
            findings.append(_f("data_availability", "OK", "数据完整性可用",
                               f"{n} 根 bar，无缺失/零成交异常", "—", "—"))

    # ---------- 2. 成交假设 ----------
    findings.append(_f(
        "fill", "INFO",
        "成交时点：收盘生成信号 → 次日开盘成交",
        "引擎约定（signal at close(t) → fill at open(t+1)）",
        "若策略实现中用当日收盘价成交，则该笔交易用了尚未形成的收盘价（前视）",
        "自定义策略必须保证 signal 先 shift(1) 再用于成交"))

    # ---------- 3. 流动性 ----------
    if df is not None and len(df) and {"volume", "close"} <= set(df.columns):
        try:
            median_amount = float((pd.to_numeric(df["volume"], errors="coerce")
                                   * pd.to_numeric(df["close"], errors="coerce")).median())
            order_amount = capital * position_pct / 100.0
            if median_amount > 0:
                share = order_amount / median_amount
                if share > 1.0:
                    findings.append(_f("liquidity", "FATAL",
                                       "单笔委托规模超过日均成交额",
                                       f"委托 {order_amount:,.0f} / 日均成交 {median_amount:,.0f} "
                                       f"= {share:.1f} 倍",
                                       "回测假设全额成交，实盘根本不可能，收益严重虚高",
                                       "降低仓位或按成交量上限（如日均成交额 1%）限制委托"))
                elif share > 0.05:
                    findings.append(_f("liquidity", "WARN",
                                       "单笔委托占日均成交额比例偏高",
                                       f"占比 {share:.1%}",
                                       "成交会被拆单、延迟，实际均价偏离收盘价",
                                       "限制单笔 ≤ 日均成交额 1%~5%，或引入成交量约束"))
                else:
                    findings.append(_f("liquidity", "OK", "流动性充足",
                                       f"委托占日均成交 {share:.2%}", "—", "—"))
        except Exception as e:  # noqa: BLE001
            log.debug("流动性检查失败：%s", e)

    # ---------- 4. 成本 ----------
    fee = getattr(config, "fee", None)
    fee_d = fee.__dict__ if fee is not None and hasattr(fee, "__dict__") else {}
    if isinstance(fee, dict):
        fee_d = fee
    commission = _num(fee_d, "commission_rate", "commission")
    stamp = _num(fee_d, "stamp_tax_sell", "stamp_duty")
    if config is None:
        findings.append(_f("cost", "WARN", "未传入费用配置，采用默认费率",
                           "config=None",
                           "默认费率可能与实际券商不一致，影响净收益",
                           "显式传入 BacktestConfig(fee=FeeModel(...))"))
    elif commission == 0 and stamp == 0:
        findings.append(_f("cost", "WARN", "佣金与印花税均为 0（零成本回测）",
                           f"commission_rate={commission}, stamp_tax_sell={stamp}",
                           "零成本会系统性高估净收益，尤其高频策略",
                           "按实际费率建模（A 股卖出印花税不可省）"))
    else:
        findings.append(_f("cost", "OK", "成本已建模",
                           f"commission_rate={commission}, stamp_tax_sell={stamp}",
                           "—", "—"))

    # ---------- 5. 滑点 ----------
    slip = _num(fee_d, "slippage_bps", "slippage")
    if slip == 0:
        findings.append(_f("slippage", "WARN", "滑点为 0",
                           f"slippage_bps={slip}",
                           "实际成交价劣于收盘价，零滑点高估收益",
                           "设 2~10 bps（小盘/低流动性取更高值）"))
    else:
        findings.append(_f("slippage", "OK", f"滑点已建模（{slip} bps）",
                           f"slippage_bps={slip}", "—", "—"))

    # ---------- 6. 幸存者偏差 ----------
    if universe is None:
        findings.append(_f("survivorship", "INFO",
                           "未提供股票池样本说明",
                           "universe=None（单标的回测，或股票池未声明）",
                           "若多标的回测只取当下存续标的，会系统性剔除退市/被 ST 的失败样本",
                           "多标的回测必须传入当时点成分（PIT 成分表），并声明口径"))
    elif len(universe) == 1:
        findings.append(_f("survivorship", "OK", "单标的回测，不涉及样本存续偏差",
                           f"universe={universe}", "—", "—"))
    else:
        findings.append(_f("survivorship", "WARN",
                           f"股票池含 {len(universe)} 只标的，需确认是否为当时点成分",
                           f"universe 规模 {len(universe)}",
                           "若用今日成分回测历史，等于只留下当年的赢家",
                           "使用 PIT（point-in-time）成分表，或声明存在该偏差"))

    # ---------- 7. 时间对齐 ----------
    try:
        from core.chronoaudit import audit_bars
        rep = audit_bars(df if df is not None else pd.DataFrame(), market=market)
        fatal = [f for f in rep.get("findings", []) if f["severity"] == "FATAL"]
        warn = [f for f in rep.get("findings", []) if f["severity"] == "WARN"]
        if fatal:
            findings.append(_f("time_alignment", "FATAL",
                               "存在致命时间完整性缺陷",
                               "；".join(f["detail"] for f in fatal[:2]),
                               "时间轴错乱会让一切指标与成交时点失效",
                               "先修复 chronoaudit 报告的致命项"))
        elif warn:
            findings.append(_f("time_alignment", "WARN",
                               "存在时间完整性告警",
                               "；".join(f["detail"] for f in warn[:2]),
                               "时间戳口径（尤其 bar-stamping）可能导致隐性前视",
                               "核对时区与 bar 打戳约定"))
        else:
            findings.append(_f("time_alignment", "OK", "时间轴一致",
                               f"bar-stamping={rep.get('convention', {}).get('convention')}",
                               "—", "—"))
    except Exception as e:  # noqa: BLE001
        log.debug("时间对齐检查不可用：%s", e)

    # ---------- 8. 市场冲击 ----------
    if df is not None and len(df) and {"volume", "close"} <= set(df.columns):
        try:
            med_amt = float((pd.to_numeric(df["volume"], errors="coerce")
                             * pd.to_numeric(df["close"], errors="coerce")).median())
            order_amount = capital * position_pct / 100.0
            if med_amt > 0 and order_amount / med_amt > 0.01:
                findings.append(_f("market_impact", "WARN",
                                   "委托规模足以产生市场冲击（未建模）",
                                   f"委托占日均成交 {order_amount / med_amt:.1%}",
                                   "大单会推动价格，实际成交均价劣于回测假设",
                                   "引入冲击成本模型（如平方根模型）或降低单笔规模"))
            else:
                findings.append(_f("market_impact", "OK", "市场冲击可忽略",
                                   f"委托占日均成交 {order_amount / med_amt:.2%}"
                                   if med_amt > 0 else "无成交数据",
                                   "—", "—"))
        except Exception:  # noqa: BLE001
            pass

    # ---------- 9. 分红除权 ----------
    adj_col = next((c for c in ("adj_close", "adj_factor", "hfq_close", "qfq_close")
                    if df is not None and c in df.columns), None)
    if df is None:
        findings.append(_f("dividend", "INFO", "无数据，无法判断复权口径", "df=None",
                           "—", "—"))
    elif adj_col:
        findings.append(_f("dividend", "OK", f"已使用复权价（{adj_col}）",
                           f"列：{adj_col}",
                           "—", "—"))
    else:
        findings.append(_f("dividend", "WARN", "未发现复权价字段，疑似未处理除权除息",
                           f"可用列：{list(df.columns)[:8]}",
                           "除权日价格跳空会被误判为暴跌/暴涨，产生虚假信号",
                           "使用前复权/后复权序列，或显式应用除权因子"))

    counts = {"FATAL": 0, "WARN": 0, "INFO": 0, "OK": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    findings.sort(key=lambda f: (_SEV_ORDER.get(f["severity"], 9), f["id"]))
    passed = counts["FATAL"] == 0
    return {
        "dimensions": DIMENSIONS,
        "findings": findings,
        "counts": counts,
        "passed": passed,
        "covered": len({f["id"] for f in findings}),
        "summary": (f"九维假设审计：覆盖 {len({f['id'] for f in findings})}/9 维 · "
                    f"致命 {counts['FATAL']} / 警告 {counts['WARN']} / "
                    f"提示 {counts['INFO']} / 通过 {counts['OK']}"),
    }


def format_report(rep: Dict[str, Any]) -> str:
    """人读报告：缺陷 × 证据 × 严重度 × 影响 × 修复。"""
    lines = [rep["summary"]]
    for f in rep["findings"]:
        if f["severity"] == "OK":
            continue
        mark = {"FATAL": "⛔", "WARN": "⚠️", "INFO": "ℹ️"}.get(f["severity"], "·")
        lines.append(f"\n{mark} [{f['severity']}] {f['id']} · {f['defect']}")
        lines.append(f"  证据：{f['evidence']}")
        if f["impact"] and f["impact"] != "—":
            lines.append(f"  影响：{f['impact']}")
        if f["fix"] and f["fix"] != "—":
            lines.append(f"  修复：{f['fix']}")
    if not rep["passed"]:
        lines.append("\n⛔ 存在致命假设缺陷：该回测结论不可用于任何决策")
    return "\n".join(lines)
