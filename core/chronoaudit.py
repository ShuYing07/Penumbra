# -*- coding: utf-8 -*-
"""时间完整性审计（chronoaudit）：专门抓"静默损坏回测"的时间类缺陷。

为什么单独做这一层：
前视偏差、过拟合这些"明星问题"有成熟工具盯，但**时间完整性缺陷**几乎没人查——
它不会报错、不会让收益变负，只会让回测在错误的时间轴上算出漂亮的数：

- 夏令时（DST）切换导致的重复/缺失小时；
- 供应商按 UTC 打戳、程序按本地时间解读（A 股日线凭空差 8 小时）；
- bar-stamping 约定混乱：日线的戳是"开盘时刻"还是"收盘时刻"？
  若戳在 15:00（收盘），那么**同一天 09:30 的决策就不该看到这根 bar 的收盘价**——
  这正是最隐蔽的一类前视偏差。

参考 chronoaudit 的方法论：不猜意图，只**测量数据的实际表现**，
把每个矛盾报为发现项并标注 INFO / WARN / FATAL，不合格数据拒绝进入回测。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

log = logging.getLogger("stockai.chronoaudit")

# A 股交易时段（用于 bar-stamping 约定判定与日内戳校验）
CN_SESSIONS = (("09:30", "11:30"), ("13:00", "15:00"))
_WEEKEND = {5, 6}  # 周六/周日


def _finding(rule_id: str, name: str, severity: str, detail: str,
             impact: str, fix: str, samples: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"rule_id": rule_id, "name": name, "severity": severity,
            "detail": detail, "impact": impact, "fix": fix,
            "samples": samples or []}


def _offsets(idx: pd.DatetimeIndex) -> Optional[List[int]]:
    """取每个时间戳的 UTC 偏移（分钟）；naive 索引返回 None。"""
    if getattr(idx, "tz", None) is None:
        return None
    try:
        return [int(off.total_seconds() // 60) for off in idx.map(lambda t: t.utcoffset())]
    except Exception:  # noqa: BLE001
        return None


def detect_bar_stamping(idx: pd.DatetimeIndex) -> Dict[str, Any]:
    """判定 bar-stamping 约定：日线戳是"交易日零点"还是"含日内时刻（开盘/收盘）"。

    返回 {convention, confidence, note}。convention ∈ date_only / open / close / intraday
    """
    if len(idx) == 0:
        return {"convention": "unknown", "confidence": 0.0, "note": "空数据"}
    times = pd.Series([t.time() for t in idx])
    midnight = sum(1 for t in times if t.hour == 0 and t.minute == 0 and t.second == 0)
    ratio_midnight = midnight / len(times)
    if ratio_midnight > 0.95:
        return {"convention": "date_only", "confidence": round(ratio_midnight, 3),
                "note": "时间戳落在交易日零点：日线 bar 以「交易日」标识，收盘价在当日收盘后可知"}
    # 含日内时刻 → 看更像开盘还是收盘
    minutes = pd.Series([t.hour * 60 + t.minute for t in times])
    med = int(minutes.median())
    if 14 * 60 <= med <= 15 * 60 + 30:
        return {"convention": "close", "confidence": 0.6,
                "note": f"时间戳中位数 {med//60:02d}:{med%60:02d} 接近收盘时刻："
                        "bar 以收盘时点打戳，该 bar 的收盘价**在其时间戳时刻才可知**"}
    if 9 * 60 <= med <= 10 * 60:
        return {"convention": "open", "confidence": 0.6,
                "note": f"时间戳中位数 {med//60:02d}:{med%60:02d} 接近开盘时刻："
                        "bar 以开盘时点打戳，注意该 bar 的收盘价要到收盘后才可知"}
    return {"convention": "intraday", "confidence": 0.5,
            "note": f"时间戳含日内时刻（中位数 {med//60:02d}:{med%60:02d}），"
                    "需确认是分钟/小时线还是日线错带时刻"}


def audit_bars(df: pd.DataFrame, market: str = "CN", freq: str = "1d",
               max_gap_days: int = 10) -> Dict[str, Any]:
    """对行情数据做时间完整性审计。

    返回：{passed, severity, counts, findings, convention, meta}
    - passed=False → 建议拒绝进入回测（存在 FATAL）
    """
    out: Dict[str, Any] = {"passed": True, "severity": "INFO",
                           "counts": {"FATAL": 0, "WARN": 0, "INFO": 0},
                           "findings": [], "convention": {}, "meta": {}}
    if df is None or len(df) == 0:
        out.update({"passed": False, "severity": "FATAL", "meta": {"rows": 0}})
        out["findings"].append(_finding(
            "C00", "空数据", "FATAL", "行情数据为空",
            "无法进行任何回测或分析", "检查数据源与拉取参数"))
        out["counts"]["FATAL"] += 1
        return out

    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            df = df.copy()
            df.index = idx
        except Exception as e:  # noqa: BLE001
            out.update({"passed": False, "severity": "FATAL"})
            out["findings"].append(_finding(
                "C00", "索引非时间类型", "FATAL", f"无法转换为时间索引：{e}",
                "所有时间对齐检查都失效", "确保索引为 DatetimeIndex"))
            out["counts"]["FATAL"] += 1
            return out

    rows = len(idx)
    findings: List[Dict[str, Any]] = []

    # C01 重复时间戳
    dup_mask = idx.duplicated(keep=False)
    n_dup = int(dup_mask.sum())
    if n_dup:
        samples = [str(t) for t in idx[dup_mask][:5]]
        findings.append(_finding(
            "C01", "重复时间戳", "FATAL",
            f"存在 {n_dup} 个重复时间戳（示例：{', '.join(samples[:3])}）",
            "同一时点被计入两次，成交量/收益被重复计算，回测结果失真",
            "去重（保留最后一条）或向数据源核查重复推送"))

    # C02 时间倒序
    if not idx.is_monotonic_increasing:
        bad = [i for i in range(1, rows) if idx[i] < idx[i - 1]][:5]
        samples = [f"{idx[i-1]} → {idx[i]}" for i in bad]
        findings.append(_finding(
            "C02", "时间倒序", "FATAL",
            f"索引非单调递增，共 {len(bad)} 处倒序（示例：{samples[:2]}）",
            "回测按时间推进，倒序会让「未来」数据被提前使用",
            "按时间排序并重设索引（sort_index）"))

    # C03 未来时间戳
    now = pd.Timestamp.now(tz=idx.tz) if getattr(idx, "tz", None) else pd.Timestamp.now()
    future = [str(t) for t in idx if t > now][:5]
    if future:
        findings.append(_finding(
            "C03", "未来时间戳", "FATAL",
            f"存在晚于当前时间的戳：{', '.join(future[:3])}",
            "数据源时钟错误或数据被污染，任何回测结论都不可信",
            "检查数据源时钟与本地时区设置"))

    # C04 周末/非交易日（日线 A 股）
    if market.upper() in ("CN", "A", "A股") and freq == "1d":
        wk = [str(t.date()) for t in idx if t.weekday() in _WEEKEND][:5]
        if wk:
            findings.append(_finding(
                "C04", "非交易日数据", "WARN",
                f"存在周末日期的 bar：{', '.join(wk[:3])}",
                "A 股周末不开市，说明时区解读错误或数据源混入脏数据",
                "核对时区（应以上交所/深交所本地时间解读）并剔除"))

    # C05 时间间隔跳跃
    if rows > 2:
        deltas = pd.Series(idx).diff().dropna()
        med = deltas.median()
        if pd.notna(med) and med > pd.Timedelta(0):
            big = deltas[deltas > med * 5]
            if len(big):
                samples = [f"{idx[i-1].date()}→{idx[i].date()}" for i in big.index[:5]]
                findings.append(_finding(
                    "C05", "时间戳跳跃", "WARN",
                    f"{len(big)} 处间隔超过中位数({med})的 5 倍（示例：{samples[:3]}）",
                    "可能是停牌、数据缺失或供应商漏推；缺失区间会让指标计算跨期拼接",
                    "补齐缺失区间或显式标注停牌，避免在缺口两侧直接算收益率"))

    # C06 时区/夏令时漂移
    offs = _offsets(idx)
    if offs:
        uniq = sorted(set(offs))
        if len(uniq) > 1:
            findings.append(_finding(
                "C06", "时区偏移漂移（含 DST）", "WARN",
                f"UTC 偏移出现 {len(uniq)} 种取值：{uniq}（分钟）",
                "夏令时切换或时区标注不一致，会让日内序列出现重复/缺失小时",
                "统一转换为 UTC 再按交易所时区重打戳（tz_convert）"))

    # C07 bar-stamping 约定
    conv = detect_bar_stamping(idx)
    if conv["convention"] == "close":
        findings.append(_finding(
            "C07", "bar 以收盘时点打戳", "WARN",
            conv["note"],
            "若决策发生在同一天的开盘/盘中，就会用到「当日收盘价」——隐蔽的前视偏差",
            "把该 bar 的可用性时点设为'戳 + 收盘时刻'，或统一改用交易日零点打戳"))
    elif conv["convention"] == "intraday" and freq == "1d":
        findings.append(_finding(
            "C07", "日线携带日内时刻", "INFO",
            conv["note"],
            "日线却带日内时间戳，容易在时间对齐时差一天",
            "统一规范化为交易日（normalize）"))

    # C08 频率一致性
    if rows > 3:
        deltas = pd.Series(idx).diff().dropna()
        if len(deltas):
            mode = deltas.mode()
            med = deltas.median()
            if len(mode) and pd.notna(med) and mode.iloc[0] != med:
                findings.append(_finding(
                    "C08", "采样频率不一致", "INFO",
                    f"间隔众数 {mode.iloc[0]} 与中位数 {med} 不一致",
                    "混合频率会让年化/波动率换算失真",
                    "重采样到统一频率后再计算指标"))

    for f in findings:
        out["counts"][f["severity"]] = out["counts"].get(f["severity"], 0) + 1
    out["findings"] = findings
    out["convention"] = conv
    out["meta"] = {"rows": rows, "market": market, "freq": freq,
                   "tz": str(getattr(idx, "tz", None)),
                   "start": str(idx[0]), "end": str(idx[-1])}
    if out["counts"]["FATAL"]:
        out.update({"passed": False, "severity": "FATAL"})
    elif out["counts"]["WARN"]:
        out.update({"severity": "WARN"})
    return out


def gate(df: pd.DataFrame, market: str = "CN", freq: str = "1d") -> Dict[str, Any]:
    """回测准入闸门：不合格数据拒绝进入回测。"""
    rep = audit_bars(df, market=market, freq=freq)
    return {"admitted": rep["passed"], "reason": "" if rep["passed"]
            else "；".join(f["detail"] for f in rep["findings"] if f["severity"] == "FATAL"),
            "report": rep}


def format_report(rep: Dict[str, Any]) -> str:
    """人读报告（供 UI/日志展示）。"""
    c = rep["counts"]
    lines = [f"时间完整性审计 · {rep['meta'].get('rows', 0)} 根 bar · "
             f"致命 {c.get('FATAL',0)} / 警告 {c.get('WARN',0)} / 提示 {c.get('INFO',0)}",
             f"区间：{rep['meta'].get('start','-')} → {rep['meta'].get('end','-')} "
             f"（tz={rep['meta'].get('tz')}）"]
    conv = rep.get("convention") or {}
    if conv.get("convention"):
        lines.append(f"bar-stamping 约定：{conv['convention']} —— {conv.get('note','')}")
    if not rep["findings"]:
        lines.append("✅ 未发现时间完整性缺陷")
        return "\n".join(lines)
    for f in rep["findings"]:
        lines.append(f"\n[{f['severity']}] {f['rule_id']} {f['name']}")
        lines.append(f"  现象：{f['detail']}")
        lines.append(f"  影响：{f['impact']}")
        lines.append(f"  修复：{f['fix']}")
    if not rep["passed"]:
        lines.append("\n⛔ 存在致命时间缺陷，建议拒绝进入回测")
    return "\n".join(lines)
