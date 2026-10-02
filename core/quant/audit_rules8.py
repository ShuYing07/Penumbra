# -*- coding: utf-8 -*-
"""回测八条分级审计规则（2026-10 翻新 · 模块二升级版）。

在历轮已落地的审计能力（scan_lookahead / walk_forward / negative_control /
guard_checklist）之上，按 quant-backtest-guard「照妖镜」与 fin-skills
五门审计（universe/timestamps/labels/costs/trials）的最新实践，把八条规则
全部实现为**可计算的独立检查**，并输出「诚实结果 vs 被偏差吹大的结果」
并排对比。

八条规则（固有严重度 → 触发即按该级上报）：
1. 前视偏差 lookahead          —— 致命：截断未来数据重算信号比对
2. 幸存者偏差 survivorship      —— 提示：样本覆盖长度/区间完整性
3. 过拟合 overfitting          —— 高危：Walk-Forward 样本外退化
4. 数据窥探 data_snooping      —— 高危：阴性对照不显著（收益可能来自运气）
5. 多重检验 multiple_testing    —— 提示：按试错次数收紧显著性门槛（Bonferroni）
6. 成本忽视 cost_neglect        —— 高危：零费/零滑点对照，成本吞噬率过高
7. 流动性假设 liquidity         —— 高危：单笔成交金额占当日成交额比例失真
8. 时间对齐 time_alignment      —— 致命：索引乱序/重复/未来日期/非交易日

输出 {grade, score, rules: [{id, name, severity, status, detail, evidence}],
summary, passed, honest_vs_inflated}。全部为确定性规则，不依赖 LLM。
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from core.quant.audit import scan_lookahead, walk_forward
from core.quant.backtest import (BacktestConfig, FeeModel, run_backtest)
from core.quant.nullius import negative_control

log = logging.getLogger("stockai.quant.audit8")

# 规则固有严重度（触发 fail 时按此级别上报）
RULE_SEVERITY: Dict[str, str] = {
    "lookahead": "critical",
    "survivorship": "info",
    "overfitting": "high",
    "data_snooping": "high",
    "multiple_testing": "info",
    "cost_neglect": "high",
    "liquidity": "high",
    "time_alignment": "critical",
}

ZERO_FEE = FeeModel(commission_rate=0.0, min_commission=0.0,
                    stamp_tax_sell=0.0, transfer_fee=0.0, slippage_bps=0.0)


def _f(x, default: float = 0.0) -> float:
    """nan 安全的 float 转换。"""
    try:
        v = float(x)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 八条规则（每条返回 {id, name, severity, status, detail, evidence}）
# ---------------------------------------------------------------------------

def _rule(rule_id: str, name: str, status: str, detail: str,
          evidence: Optional[dict] = None) -> Dict[str, Any]:
    return {"id": rule_id, "name": name, "severity": RULE_SEVERITY[rule_id],
            "status": status, "detail": detail, "evidence": evidence or {}}


def rule_lookahead(df: pd.DataFrame, strategy: str,
                   params: Optional[dict]) -> Dict[str, Any]:
    """1. 前视偏差（致命）：截断未来数据重算信号。"""
    r = scan_lookahead(df, strategy, params)
    v = r.get("verdict", "na")
    status = {"pass": "pass", "suspect": "warn", "fail": "fail"}.get(v, "na")
    return _rule("lookahead", "前视偏差（未来函数）", status,
                 f"检查 {r.get('checked', 0)} 个信号点，偏移 {r.get('mismatches', 0)} 个"
                 f"（ratio={r.get('ratio', 0)}）；{r.get('reason') or r.get('note', '')}",
                 {"verdict": v, "suspicious_points": r.get("detail", [])[:5]})


def rule_survivorship(df: pd.DataFrame) -> Dict[str, Any]:
    """2. 幸存者偏差（提示）：样本覆盖长度。"""
    n = len(df)
    if n < 120:
        return _rule("survivorship", "幸存者偏差（样本覆盖）", "warn",
                     f"仅 {n} 根数据，样本过短，无法排除幸存者偏差；"
                     f"若股票池按当下存续标的构建，结论为收益上界",
                     {"bars": n})
    years = round(n / 252, 1)
    return _rule("survivorship", "幸存者偏差（样本覆盖）", "pass",
                 f"{n} 根数据（约 {years} 年），覆盖基本充分；"
                 f"注意：单标的回测本身不含退市股票，组合结论需另作 Universe 审计",
                 {"bars": n, "years": years})


def rule_overfitting(df: pd.DataFrame, market: str, strategy: str,
                     params: Optional[dict], config) -> Dict[str, Any]:
    """3. 过拟合（高危）：Walk-Forward 样本外退化。"""
    wf = walk_forward(df, market, strategy, params, config)
    if "error" in wf:
        return _rule("overfitting", "过拟合（样本外退化）", "na",
                     f"Walk-Forward 不可用：{wf['error']}")
    in_ret = _f(wf["in"].get("annual_return_pct")
                or wf["in"].get("total_return_pct"))
    out_ret = _f(wf["out"].get("annual_return_pct")
                 or wf["out"].get("total_return_pct"))
    degrade = in_ret - out_ret
    ev = {"in_annual": in_ret, "out_annual": out_ret,
          "split_date": wf.get("split_date")}
    if in_ret > 0 and out_ret < 0:
        return _rule("overfitting", "过拟合（样本外退化）", "fail",
                     f"样本内年化 {in_ret:+.2%} 为正，样本外 {out_ret:+.2%} 转负"
                     f"——策略疑似过拟合历史", ev)
    if in_ret > 0 and out_ret < in_ret * 0.5:
        return _rule("overfitting", "过拟合（样本外退化）", "warn",
                     f"样本外年化 {out_ret:+.2%} 不足样本内 {in_ret:+.2%} 的一半"
                     f"（退化 {degrade:+.2%}）", ev)
    return _rule("overfitting", "过拟合（样本外退化）", "pass",
                 f"样本内 {in_ret:+.2%} / 样本外 {out_ret:+.2%} 年化，无显著退化", ev)


def rule_data_snooping(df: pd.DataFrame, market: str, strategy: str,
                       params: Optional[dict], config,
                       n_perm: int = 200) -> Dict[str, Any]:
    """4. 数据窥探（高危）：阴性对照——真实策略须显著优于随机信号。"""
    try:
        nc = negative_control(df, market, strategy, params, config, n_perm=n_perm)
    except Exception as e:  # noqa: BLE001
        return _rule("data_snooping", "数据窥探（阴性对照）", "na",
                     f"阴性对照不可计算：{e}")
    if "error" in nc:
        return _rule("data_snooping", "数据窥探（阴性对照）", "na",
                     f"阴性对照不可用：{nc['error']}")
    pct = float(nc.get("percentile", 0.0))
    z = float(nc.get("z_score", 0.0))
    ev = {"percentile": pct, "z_score": z, "n_perm": n_perm}
    if not nc.get("significant", False):
        return _rule("data_snooping", "数据窥探（阴性对照）", "fail",
                     f"真实策略收益百分位 {pct:.0f}%（z={z:.2f}），未显著优于随机信号"
                     f"——收益可能来自运气/数据窥探", ev)
    return _rule("data_snooping", "数据窥探（阴性对照）", "pass",
                 f"真实策略显著优于随机信号（百分位 {pct:.0f}%，z={z:.2f}）", ev)


def rule_multiple_testing(n_trials: int = 1,
                          observed_percentile: Optional[float] = None
                          ) -> Dict[str, Any]:
    """5. 多重检验（提示）：按试错次数收紧显著性门槛（Bonferroni 校正）。

    n_trials：开发过程中实际尝试过的策略/参数组合总数（含被丢弃的）。
    observed_percentile：阴性对照给出的真实策略百分位（0~100），可选。
    """
    n_trials = max(1, int(n_trials))
    if n_trials <= 1:
        return _rule("multiple_testing", "多重检验（试错校正）", "pass",
                     "单次实验，无需多重检验校正", {"n_trials": 1})
    # Bonferroni：家族显著性 5% → 单次门槛 5%/n_trials → 要求百分位
    required_pct = 100.0 * (1.0 - 0.05 / n_trials)
    ev = {"n_trials": n_trials, "required_percentile": round(required_pct, 2)}
    detail = (f"已试错 {n_trials} 组策略/参数，Bonferroni 校正后要求百分位 "
              f"≥ {required_pct:.1f}%")
    if observed_percentile is not None:
        ev["observed_percentile"] = observed_percentile
        if observed_percentile < required_pct:
            return _rule("multiple_testing", "多重检验（试错校正）", "warn",
                         detail + f"；当前 {observed_percentile:.0f}% 未达校正门槛"
                                  f"——显著性可能是多次试错的产物", ev)
        return _rule("multiple_testing", "多重检验（试错校正）", "pass",
                     detail + f"；当前 {observed_percentile:.0f}% 通过校正门槛", ev)
    status = "warn" if n_trials >= 10 else "pass"
    return _rule("multiple_testing", "多重检验（试错校正）", status,
                 detail + "（未提供观测百分位，仅提示校正门槛）", ev)


def rule_cost_neglect(df: pd.DataFrame, market: str, strategy: str,
                      params: Optional[dict], config) -> Dict[str, Any]:
    """6. 成本忽视（高危）：诚实回测 vs 零费零滑点对照，计算成本吞噬率。"""
    try:
        honest = run_backtest(df, market, strategy, params or None, config)
        cfg_free = BacktestConfig(
            market=market, fee=ZERO_FEE,
            init_capital=(config.init_capital if config else 1_000_000.0),
            position_pct=(config.position_pct if config else 100.0))
        free = run_backtest(df, market, strategy, params or None, cfg_free)
    except Exception as e:  # noqa: BLE001
        return _rule("cost_neglect", "成本忽视（费用对照）", "na",
                     f"费用对照不可计算：{e}")
    net = _f(honest.metrics.get("total_return_pct"))
    gross = _f(free.metrics.get("total_return_pct"))
    drag = gross - net
    drag_ratio = (drag / abs(gross)) if abs(gross) > 1e-9 else 0.0
    ev = {"net_return": net, "zero_fee_return": gross,
          "cost_drag": drag, "drag_ratio": round(drag_ratio, 3)}
    if gross > 0 and net <= 0:
        return _rule("cost_neglect", "成本忽视（费用对照）", "fail",
                     f"零费收益 {gross:+.2%} 为正，计入真实成本后 {net:+.2%} 转负"
                     f"——策略利润被交易成本完全吞噬", ev)
    if gross > 0 and drag_ratio > 0.3:
        return _rule("cost_neglect", "成本忽视（费用对照）", "warn",
                     f"交易成本吞噬毛收益的 {drag_ratio:.0%}"
                     f"（零费 {gross:+.2%} → 诚实 {net:+.2%}）", ev)
    return _rule("cost_neglect", "成本忽视（费用对照）", "pass",
                 f"成本吞噬率 {drag_ratio:.0%}（零费 {gross:+.2%} → 诚实 {net:+.2%}），"
                 f"在可接受范围", ev)


def rule_liquidity(df: pd.DataFrame, market: str, strategy: str,
                   params: Optional[dict], config,
                   max_participation: float = 0.10) -> Dict[str, Any]:
    """7. 流动性假设（高危）：单笔成交金额不得超过当日成交额的一定比例。"""
    if "volume" not in df.columns:
        return _rule("liquidity", "流动性假设", "na", "数据无 volume 列，跳过流动性检查")
    try:
        res = run_backtest(df, market, strategy, params or None, config)
    except Exception as e:  # noqa: BLE001
        return _rule("liquidity", "流动性假设", "na", f"回测不可用：{e}")
    vol = df["volume"].astype(float)
    zero_vol_days = int((vol <= 0).sum())
    trades = res.trades
    worst_ratio, worst_day = 0.0, None
    if trades is not None and len(trades) and "amount" in trades.columns:
        day_dollar_vol = (vol * df["close"].astype(float))
        for _, tr in trades.iterrows():
            d = tr.get("fill_date") or tr.get("date")
            try:
                dv = float(day_dollar_vol.get(pd.Timestamp(d), np.nan))
            except Exception:  # noqa: BLE001
                continue
            if dv and np.isfinite(dv) and dv > 0:
                ratio = float(tr.get("amount", 0.0)) / dv
                if ratio > worst_ratio:
                    worst_ratio, worst_day = ratio, str(d)
    ev = {"worst_participation": round(worst_ratio, 4), "worst_day": worst_day,
          "zero_volume_days": zero_vol_days}
    if worst_ratio > max_participation:
        return _rule("liquidity", "流动性假设", "fail",
                     f"最大单笔成交占当日成交额 {worst_ratio:.1%}（{worst_day}），"
                     f"超过 {max_participation:.0%} 参与率上限——成交价格假设失真", ev)
    if zero_vol_days > 0:
        return _rule("liquidity", "流动性假设", "warn",
                     f"存在 {zero_vol_days} 个零成交量交易日，这些日的成交假设存疑", ev)
    return _rule("liquidity", "流动性假设", "pass",
                 f"最大单笔参与率 {worst_ratio:.1%}，低于 {max_participation:.0%} 上限", ev)


def rule_time_alignment(df: pd.DataFrame, market: str) -> Dict[str, Any]:
    """8. 时间对齐（致命）：索引单调、无重复、无未来日期、无非交易日。"""
    issues: List[str] = []
    idx = df.index
    if not idx.is_monotonic_increasing:
        issues.append("时间索引非单调递增（存在乱序）")
    if idx.has_duplicates:
        issues.append(f"存在 {int(idx.duplicated().sum())} 个重复时间戳")
    try:
        last = pd.Timestamp(idx[-1])
        if last > pd.Timestamp.now() + pd.Timedelta(days=1):
            issues.append(f"最后一根 K 线日期 {last.date()} 晚于今天——数据来自未来")
    except Exception:  # noqa: BLE001
        pass
    if market == "CN":
        try:
            weekends = int((idx.dayofweek >= 5).sum())
            if weekends:
                issues.append(f"A股数据包含 {weekends} 个周末日期（非交易日对齐异常）")
        except Exception:  # noqa: BLE001
            pass
    if issues:
        return _rule("time_alignment", "时间对齐", "fail",
                     "；".join(issues), {"issues": issues})
    return _rule("time_alignment", "时间对齐", "pass",
                 "索引单调递增、无重复、无未来日期、无周末交易日")


# ---------------------------------------------------------------------------
# 诚实结果 vs 被偏差吹大的结果（并排对比）
# ---------------------------------------------------------------------------

def honest_vs_inflated(df: pd.DataFrame, market: str, strategy: str,
                       params: Optional[dict] = None, config=None) -> Dict[str, Any]:
    """并排展示：诚实回测（费用+滑点+整手+T+1）vs 吹大回测（零费零滑点）。

    返回 {honest, inflated, gap, verdict}。差距即「偏差吹大的泡沫」。
    """
    honest = run_backtest(df, market, strategy, params or None, config)
    cfg_free = BacktestConfig(
        market=market, fee=ZERO_FEE,
        init_capital=(config.init_capital if config else 1_000_000.0),
        position_pct=(config.position_pct if config else 100.0))
    inflated = run_backtest(df, market, strategy, params or None, cfg_free)

    def _pick(m: dict) -> dict:
        return {k: m.get(k) for k in
                ("total_return_pct", "annual_return_pct", "sharpe",
                 "max_drawdown_pct", "win_rate_pct", "trade_count")
                if k in m}

    h, i = _pick(honest.metrics), _pick(inflated.metrics)
    gap = {}
    for k in h:
        hv, iv = _f(h[k], None), _f(i.get(k), None)
        if hv is not None and iv is not None:
            gap[k] = round(iv - hv, 6)
    verdict = "诚实结果与吹大结果差距可控"
    h_ret = _f(h.get("total_return_pct")) / 100.0
    i_ret = _f(i.get("total_return_pct")) / 100.0
    if h_ret <= 0 < i_ret:
        verdict = "吹大结果为正、诚实结果为负——收益幻象完全来自成本忽视"
    elif abs(gap.get("total_return_pct", 0.0)) > 10.0:
        verdict = f"成本/滑点吹大了 {gap['total_return_pct']:+.1f}pct 总收益"
    return {"honest": h, "inflated": i, "gap": gap, "verdict": verdict}


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def audit8(df: pd.DataFrame, market: str, strategy: str,
           params: Optional[dict] = None, config=None,
           n_perm: int = 200, n_trials: int = 1) -> Dict[str, Any]:
    """八条分级审计 + 诚实/吹大对比。

    返回 {grade, score, rules, summary, passed, honest_vs_inflated}。
    grade: A（全部通过）/ B（有提示）/ C（有高危）/ D（有致命）。
    """
    rules: List[Dict[str, Any]] = [
        rule_time_alignment(df, market),
        rule_lookahead(df, strategy, params),
        rule_survivorship(df),
        rule_overfitting(df, market, strategy, params, config),
    ]
    # 数据窥探 + 多重检验（联动：阴性对照百分位作为多重检验观测值）
    snoop = rule_data_snooping(df, market, strategy, params, config, n_perm)
    rules.append(snoop)
    obs_pct = (snoop.get("evidence") or {}).get("percentile")
    rules.append(rule_multiple_testing(n_trials, obs_pct))
    rules.append(rule_cost_neglect(df, market, strategy, params, config))
    rules.append(rule_liquidity(df, market, strategy, params, config))

    critical = sum(1 for r in rules if r["status"] == "fail"
                   and r["severity"] == "critical")
    high = sum(1 for r in rules if r["status"] == "fail"
               and r["severity"] == "high")
    warns = sum(1 for r in rules if r["status"] == "warn")
    score = max(0, 100 - critical * 30 - high * 15 - warns * 5)
    grade = ("D" if critical else "C" if high else "B" if warns else "A")
    passed = critical == 0 and high == 0
    try:
        hvi = honest_vs_inflated(df, market, strategy, params, config)
    except Exception as e:  # noqa: BLE001
        hvi = {"error": f"对比不可计算：{e}"}
    summary = (f"八条审计：{grade} 级（{score}/100），致命 {critical} / "
               f"高危 {high} / 提示 {warns}；{hvi.get('verdict', '')}")
    return {"grade": grade, "score": score, "rules": rules, "summary": summary,
            "passed": passed, "honest_vs_inflated": hvi}


def format_audit8(report: Dict[str, Any]) -> str:
    """人类可读的八条审计报告文本。"""
    lines = [f"回测八条审计：{report['grade']} 级（{report['score']}/100）"]
    icon = {"pass": "✓", "warn": "⚠", "fail": "✗", "na": "—"}
    sev_cn = {"critical": "致命", "high": "高危", "info": "提示"}
    for r in report["rules"]:
        lines.append(f"  {icon.get(r['status'], '?')} [{sev_cn[r['severity']]}] "
                     f"{r['name']}：{r['detail']}")
    hvi = report.get("honest_vs_inflated") or {}
    if "honest" in hvi:
        lines.append("诚实 vs 吹大：")
        lines.append(f"  诚实：{hvi['honest']}")
        lines.append(f"  吹大：{hvi['inflated']}")
        lines.append(f"  判定：{hvi['verdict']}")
    return "\n".join(lines)


if __name__ == "__main__":
    rng = np.random.default_rng(11)
    n = 300
    bidx = pd.bdate_range("2024-01-01", periods=n)
    # 正弦振荡 + 温和趋势：保证均线策略产生多次金叉死叉信号
    wave = np.sin(np.linspace(0, 6 * np.pi, n)) * 15
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.004, n)) + wave,
                      index=bidx)
    bars = pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": rng.integers(1e5, 5e5, n)},
                        index=bidx)
    rep = audit8(bars, "CN", "ma_cross", n_perm=40)
    assert rep["grade"] in ("A", "B", "C", "D")
    assert len(rep["rules"]) == 8
    assert {r["id"] for r in rep["rules"]} == set(RULE_SEVERITY)
    print(format_audit8(rep))
