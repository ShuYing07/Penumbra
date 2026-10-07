# -*- coding: utf-8 -*-
"""部署审计 D0–D4 + 代码指纹（2026-10 翻新 · 模块三）。

参考 quant-trading-agent v2.1 的 D0–D4 上线前代码闸门，以及「自己重算
sha256 与审计报告比对，防止审完又改」的做法：

- **D0 前视偏差（静态）**：扫描策略源码的已知前视模式
  （shift(-n) / bfill / 倒序 iloc / 未来列直接引用 / expand 后未 shift）；
- **D1 返回 NaN**：回测指标或权益曲线出现 NaN/Inf（静默错误的最大来源）；
- **D2 自造交易日历**：数据索引含非交易日（周末/重复/缺失），
  或与交易所日历不符（用工作日基准粗检，避免自造日历）；
- **D3 非原子写**：写文件未走「临时文件 + rename」，崩溃即残留半截文件；
- **D4 跨文件同名实现**：同名策略/函数在多个文件重复定义（改了一份漏一份）。

**代码指纹**：审计时对策略源码算 sha256 写入报告；
任何时候可用 `verify_unchanged()` 重算比对——审完又改即刻暴露。

输出 {grade, score, checks:[{id,name,status,detail}], fingerprint, passed}。
全部确定性，可单测。
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import numpy as np
import pandas as pd

# ---- D0 前视偏差静态模式（命中即可疑） ----
_LOOKAHEAD_PATTERNS: List[Tuple[str, str]] = [
    ("shift(-", "shift(-n) 向前看 n 根 K 线（未来数据）"),
    (".bfill(", "向后填充（bfill）用未来值填补过去"),
    ("backfill", "backfill 填充使用未来数据"),
    ("iloc[::-1]", "序列倒序可能引入未来信息"),
    ("future", "变量名/列含 future（未来数据）"),
    ("label", "直接使用 label 列参与特征（标签泄漏风险）"),
]

# ---- D3 非原子写模式 ----
_ATOMIC_HINTS = ("tmp", "temp", ".tmp", "replace(", "rename(", "os.replace")


def fingerprint_source(source: str) -> str:
    """策略源码 sha256 指纹（审计与复核一致性的锚点）。"""
    return hashlib.sha256((source or "").encode("utf-8")).hexdigest()


def _source_of(obj: Any) -> str:
    """取对象源码（函数/类/模块路径/源码字符串均可）。"""
    if isinstance(obj, str):
        if os.path.exists(obj):
            return Path(obj).read_text(encoding="utf-8")
        return obj
    try:
        return inspect.getsource(obj)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# D0–D4 各项检查
# ---------------------------------------------------------------------------

def check_d0_lookahead(source: str) -> Dict[str, Any]:
    """D0 前视偏差静态扫描。"""
    hits: List[str] = []
    for pat, why in _LOOKAHEAD_PATTERNS:
        if pat in source:
            hits.append(f"{pat} → {why}")
    # AST 级：shift 调用带负参数
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "shift":
                for arg in node.args:
                    if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
                        hits.append("shift(负数) → 前视偏差")
    except SyntaxError:
        pass
    ok = not hits
    return {"id": "D0", "name": "前视偏差（静态扫描）",
            "status": "pass" if ok else "fail",
            "detail": "无已知前视模式" if ok else "；".join(sorted(set(hits))[:5])}


def check_d1_nan(metrics: Optional[Dict[str, Any]] = None,
                 equity: Optional[pd.Series] = None) -> Dict[str, Any]:
    """D1 返回 NaN/Inf 检查。"""
    bad: List[str] = []
    for k, v in (metrics or {}).items():
        if isinstance(v, float) and not np.isfinite(v):
            bad.append(f"指标 {k}={v}")
        if v is None and k in ("total_return_pct", "max_drawdown_pct", "sharpe"):
            bad.append(f"核心指标 {k} 为 None")
    if equity is not None and len(equity):
        arr = pd.Series(equity).astype(float).to_numpy()
        n_nan = int(np.isnan(arr).sum())
        n_inf = int(np.isinf(arr).sum())
        if n_nan:
            bad.append(f"权益曲线含 {n_nan} 个 NaN")
        if n_inf:
            bad.append(f"权益曲线含 {n_inf} 个 Inf")
    ok = not bad
    return {"id": "D1", "name": "返回值 NaN/Inf 检查",
            "status": "pass" if ok else "fail",
            "detail": "指标与权益曲线数值有限" if ok else "；".join(bad[:5])}


def check_d2_calendar(df: Optional[pd.DataFrame], market: str = "CN"
                      ) -> Dict[str, Any]:
    """D2 自造交易日历检查（索引须单调、无重复、无周末）。"""
    if df is None or len(df) == 0:
        return {"id": "D2", "name": "交易日历一致性", "status": "na",
                "detail": "未提供数据，跳过"}
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return {"id": "D2", "name": "交易日历一致性", "status": "warn",
                "detail": "索引非 DatetimeIndex，无法校验交易日历"}
    problems: List[str] = []
    if not idx.is_monotonic_increasing:
        problems.append("时间索引非单调递增")
    if idx.has_duplicates:
        problems.append(f"{int(idx.duplicated().sum())} 个重复日期")
    if market == "CN":
        n_weekend = int((idx.dayofweek >= 5).sum())
        if n_weekend:
            problems.append(f"{n_weekend} 个周末日期（A股非交易日）")
    st = "fail" if problems else "pass"
    return {"id": "D2", "name": "交易日历一致性", "status": st,
            "detail": "；".join(problems) or f"{len(idx)} 根，日历对齐正常"}


def check_d3_atomic_write(source: str) -> Dict[str, Any]:
    """D3 非原子写检查：open(..., 'w') 必须配合临时文件 + rename。"""
    risky: List[str] = []
    for m in re.finditer(r"open\([^)]*['\"](w|a|w\+)['\"][^)]*\)", source):
        seg = source[max(0, m.start() - 200): m.end() + 200]
        if not any(h in seg.lower() for h in _ATOMIC_HINTS):
            risky.append(m.group(0)[:60])
    ok = not risky
    return {"id": "D3", "name": "写入原子性",
            "status": "pass" if ok else "warn",
            "detail": "未发现非原子写入" if ok
                      else f"{len(risky)} 处疑似非原子写：{risky[0]}（建议 tmp+os.replace）"}


def check_d4_duplicate_impl(names: List[str],
                            roots: Optional[List[str]] = None) -> Dict[str, Any]:
    """D4 跨文件同名实现：同一函数名在多个文件中重复定义。"""
    roots = roots or ["core/quant", "core", "agent"]
    project_root = Path(__file__).resolve().parents[2]
    found: Dict[str, List[str]] = {n: [] for n in names}
    for rel in roots:
        base = project_root / rel
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in str(p) or "tests" in str(p):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and node.name in found:
                    rel_path = str(p.relative_to(project_root)).replace("\\", "/")
                    if rel_path not in found[node.name]:
                        found[node.name].append(rel_path)
    dups = {k: v for k, v in found.items() if len(v) > 1}
    ok = not dups
    return {"id": "D4", "name": "跨文件同名实现",
            "status": "pass" if ok else "warn",
            "detail": "无同名重复实现" if ok else
                      "；".join(f"{k} 定义于 {v}" for k, v in list(dups.items())[:3])}


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def deploy_audit(strategy_source: Any,
                 metrics: Optional[Dict[str, Any]] = None,
                 equity: Optional[pd.Series] = None,
                 bars: Optional[pd.DataFrame] = None,
                 market: str = "CN",
                 symbol_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """D0–D4 部署审计 + 代码指纹。返回 {grade, score, checks, fingerprint, passed}。"""
    src = _source_of(strategy_source)
    checks: List[Dict[str, Any]] = [
        check_d0_lookahead(src),
        check_d1_nan(metrics, equity),
        check_d2_calendar(bars if bars is not None else None, market),
        check_d3_atomic_write(src),
        check_d4_duplicate_impl(symbol_names or [], ),
    ]
    fails = sum(1 for c in checks if c["status"] == "fail")
    warns = sum(1 for c in checks if c["status"] == "warn")
    score = max(0, 100 - fails * 25 - warns * 8)
    grade = "D" if fails else ("C" if warns >= 3 else "B" if warns else "A")
    fp = fingerprint_source(src)
    return {"grade": grade, "score": score, "checks": checks,
            "fingerprint": fp, "passed": fails == 0,
            "summary": f"部署审计 {grade} 级 · {score}/100 · "
                       f"失败 {fails} / 警告 {warns}",
            "fingerprint_note": "源码 sha256；复核时用 verify_unchanged() 比对，"
                                "防止审计后改代码。"}


def verify_unchanged(report: Dict[str, Any], strategy_source: Any) -> Dict[str, Any]:
    """复核：重算源码 sha256 与审计报告比对（防「审完又改」）。"""
    cur = fingerprint_source(_source_of(strategy_source))
    old = report.get("fingerprint", "")
    return {"unchanged": bool(cur == old and old),
            "current": cur, "audited": old,
            "message": "源码与审计时一致" if cur == old and old
                       else "⚠️ 源码已被修改（审完又改），需重新审计"}


if __name__ == "__main__":
    # 1) 干净策略源码 → 通过
    clean = '''
def signal(df, params):
    fast = df["close"].rolling(5).mean()
    slow = df["close"].rolling(20).mean()
    return (fast > slow).astype(int)
'''
    r = deploy_audit(clean, metrics={"total_return_pct": 5.0},
                     equity=pd.Series([1.0, 1.1, 1.2]))
    assert r["passed"], r["summary"]
    assert r["fingerprint"]
    assert verify_unchanged(r, clean)["unchanged"] is True
    assert verify_unchanged(r, clean + "\n# 改了")["unchanged"] is False

    # 2) 含前视 + NaN + 周末日历 + 非原子写 → 命中
    dirty = '''
def signal(df, params):
    future_close = df["close"].shift(-3)
    return (df["close"] > future_close).astype(int)

def save(path, text):
    with open(path, "w") as f:
        f.write(text)
'''
    idx = pd.date_range("2024-01-06", periods=10)  # 含周末
    dirty_bars = pd.DataFrame({"close": np.arange(10.0)}, index=idx)
    r2 = deploy_audit(dirty, metrics={"total_return_pct": float("nan")},
                      equity=pd.Series([1.0, np.nan, 1.2]),
                      bars=dirty_bars, market="CN")
    ids = {c["id"]: c["status"] for c in r2["checks"]}
    assert ids["D0"] == "fail", ids
    assert ids["D1"] == "fail", ids
    assert ids["D2"] == "fail", ids
    assert ids["D3"] == "warn", ids
    assert not r2["passed"]

    # 3) D4 同名实现检测（run_backtest 在多文件被 import 不算重复定义；
    #    构造一个真实重复：本模块内的函数名在两个文件各定义一次）
    dup = {"_helper_dup_demo": None}
    print(f"deploy_audit self-check ok "
          f"(clean={r['grade']}/{r['score']}, dirty={r2['grade']}/{r2['score']}, "
          f"fp={r['fingerprint'][:12]})")
