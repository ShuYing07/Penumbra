# -*- coding: utf-8 -*-
"""符号自适应估值方程发现（模块一 · 参考 mufasa）。

从财务数据（营收、净利润、利润率、增长率等）自动枚举候选估值方程，
用 R² 选出最优拟合——替代「拍脑袋估值模型」，让数据说话。

设计：
- 候选方程族：线性 / 对数线性 / 多项式 / 幂律（仅用 numpy，无新依赖）；
- 对每只股票的多期财务快照拟合「内在价值 ≈ f(特征)」；
- 输出 {best_formula, r2, params, candidates}，供基本面分析引用。

注意：这是学习/拟合工具，不构成投资建议；样本过少时返回 error。
"""
from __future__ import annotations

import itertools
import logging
from typing import Any, Dict, List, Optional

import numpy as np

log = logging.getLogger("stockai.core.quant.symbolic")

_MIN_ROWS = 4


def _polyfit(x: np.ndarray, y: np.ndarray, deg: int) -> Optional[np.ndarray]:
    try:
        return np.polyfit(x, y, deg)
    except Exception:  # noqa: BLE001
        return None


def _r2(y: np.ndarray, pred: np.ndarray) -> float:
    if len(y) < 2:
        return 0.0
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    if ss_tot <= 1e-12:
        return 1.0 if ss_res <= 1e-12 else 0.0
    return float(1 - ss_res / ss_tot)


def discover_valuation_equation(
    snapshots: List[Dict[str, float]],
    value_field: str = "value",
    feature_fields: Optional[List[str]] = None,
) -> Dict[str, object]:
    """从多期财务快照中搜索最优估值方程。

    snapshots: [{"revenue": .., "profit_margin": .., "growth": .., "value": ..}]
    value_field: 目标值字段（内在价值 / 市值 / 价格）。
    feature_fields: 参与拟合的特征；缺省取除 value 外的全部数值字段。

    返回 {"best_formula", "r2", "params", "candidates", "error"(可选)}。
    """
    if not snapshots or len(snapshots) < _MIN_ROWS:
        return {"best_formula": "", "r2": 0.0, "params": {},
                "candidates": [], "error": f"样本不足（需≥{_MIN_ROWS}期）"}
    feats = feature_fields or [
        k for k in next(iter(snapshots)) if k != value_field
        and isinstance(next(iter(snapshots))[k], (int, float))]
    if not feats:
        return {"best_formula": "", "r2": 0.0, "params": {},
                "candidates": [], "error": "无可用数值特征"}
    y = np.array([s.get(value_field) for s in snapshots], dtype=float)
    if not np.all(np.isfinite(y)) or np.std(y) <= 1e-12:
        return {"best_formula": "", "r2": 0.0, "params": {},
                "candidates": [], "error": "目标值无波动/含非法值"}

    cands: List[Dict[str, object]] = []
    for n_feat in (1, 2):
        for combo in itertools.combinations(feats, n_feat):
            xs = np.column_stack([
                np.array([s.get(f) for s in snapshots], dtype=float)
                for f in combo])
            if not np.all(np.isfinite(xs)):
                continue
            # 线性
            lin = _polyfit(xs, y, 1)
            if lin is not None:
                pred = np.polyval(lin, xs)
                cands.append({"formula": _fmt_lin(lin, list(combo)),
                              "r2": _r2(y, pred),
                              "kind": "linear", "features": list(combo)})
            # 对数线性（特征与目标须为正）
            if np.all(xs > 0) and np.all(y > 0):
                logx = np.log(xs)
                llin = _polyfit(logx, np.log(y), 1)
                if llin is not None:
                    pred = np.exp(np.polyval(llin, logx))
                    cands.append({"formula": _fmt_loglin(llin, list(combo)),
                                  "r2": _r2(y, pred), "kind": "log-linear",
                                  "features": list(combo)})
            # 多项式（单特征 deg2）
            if n_feat == 1:
                p2 = _polyfit(xs[:, 0], y, 2)
                if p2 is not None:
                    pred = np.polyval(p2, xs[:, 0])
                    cands.append({"formula": _fmt_poly2(p2, combo[0]),
                                  "r2": _r2(y, pred), "kind": "poly2",
                                  "features": list(combo)})

    if not cands:
        return {"best_formula": "", "r2": 0.0, "params": {},
                "candidates": [], "error": "无可拟合候选"}
    cands.sort(key=lambda c: float(c["r2"]), reverse=True)
    best = cands[0]
    return {"best_formula": best["formula"], "r2": float(best["r2"]),
            "kind": best["kind"], "features": best["features"],
            "candidates": cands[:10]}


def _fmt_coef(c: float) -> str:
    return f"{c:.4g}"


def _fmt_lin(coefs: np.ndarray, feats: list) -> str:
    """coefs 为 polyfit 系数（降幂）；单特征线性时 coefs=[a, b] 表示 a*x+b。"""
    if len(feats) == 1:
        a, b = float(coefs[0]), float(coefs[1])
        return f"{_fmt_coef(a)}·{feats[0]} {'+' if b >= 0 else '-'} {_fmt_coef(abs(b))}"
    # 多特征：仅支持两特征，coefs=[c1, c2] 与 column 顺序一致
    terms = []
    for c, f in zip(coefs, feats):
        terms.append(f"{_fmt_coef(float(c))}·{f}")
    return " + ".join(terms) if terms else "0"


def _fmt_loglin(coefs: np.ndarray, feats: list) -> str:
    a, b = float(coefs[0]), float(coefs[1])
    f = feats[0] if feats else "x"
    return f"exp({_fmt_coef(a)}·log({f}) {'+' if b >= 0 else '-'} {_fmt_coef(abs(b))})"


def _fmt_poly2(coefs: np.ndarray, feat: str) -> str:
    a, b, c = float(coefs[0]), float(coefs[1]), float(coefs[2])
    parts = [f"{_fmt_coef(a)}·{feat}²"]
    if b >= 0:
        parts.append(f"+ {_fmt_coef(b)}·{feat}")
    else:
        parts.append(f"- {_fmt_coef(abs(b))}·{feat}")
    if c >= 0:
        parts.append(f"+ {_fmt_coef(c)}")
    else:
        parts.append(f"- {_fmt_coef(abs(c))}")
    return " ".join(parts)


if __name__ == "__main__":
    # 自检：构造线性关系 revenue*0.3 + 50
    snaps = [{"revenue": float(r), "profit_margin": 0.2, "growth": 0.1,
              "value": r * 0.3 + 50}
             for r in np.linspace(100, 500, 8)]
    r = discover_valuation_equation(snaps)
    assert "error" not in r, r
    assert r["r2"] > 0.95, r
    assert "revenue" in r["best_formula"]
    # 样本不足
    assert "error" in discover_valuation_equation(snaps[:2])
    print("symbolic_fit self-check ok")
