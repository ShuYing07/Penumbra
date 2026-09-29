# -*- coding: utf-8 -*-
"""组合管理与优化（模块四）。

- 三种方法：均值-方差（最大夏普）/ 风险平价（等风险贡献）/ HRP（层次风险平价）。
- 引擎自动适配：已安装 skfolio 则用 skfolio（engine="skfolio"）；
  否则用内置 numpy/scipy 实现（engine="numpy"），无需额外依赖。
- 约束：单只股票最大权重 max_weight（默认 0.4）、权重和=1、非负。
- 输出：权重、预期年化收益、年化波动、夏普、风险贡献分解、有效前沿采样（可选）。
- 组合回测：历史价格 → 加权组合净值 → 绩效指标。

全部输出为客观计算，不构成投资建议。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("stockai.portfolio")


def _has_skfolio() -> bool:
    try:
        import skfolio  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# 内置 numpy/scipy 实现
# ---------------------------------------------------------------------------

def _np_mean_variance(returns: np.ndarray, max_w: float, rf: float) -> np.ndarray:
    """最大夏普（解析起步 + 边界投影归一化）；无正超额收益时退最小方差。"""
    n = returns.shape[1]
    mu = returns.mean(axis=0)
    cov = np.cov(returns, rowvar=False)
    cov = cov + np.eye(n) * 1e-9
    try:
        inv = np.linalg.pinv(cov)
        w = inv @ (mu - rf)
        w = np.maximum(w, 0)
        s = w.sum()
        if s <= 0:
            # 全部负超额 → 退全局最小方差组合（非负截断）
            w = np.maximum(inv @ np.ones(n), 0)
            s = w.sum()
        if s > 0:
            w = w / s
        else:
            w = np.full(n, 1.0 / n)
    except Exception:  # noqa: BLE001
        w = np.full(n, 1.0 / n)
    # 单只上限投影（截断后重新归一化，最多 5 轮）
    for _ in range(5):
        over = w > max_w
        if not over.any():
            break
        cap = max_w
        w[over] = cap
        rest = w[~over]
        w[~over] = rest / rest.sum() * (1 - cap * over.sum()) if rest.sum() > 0 else rest
    return w


def _np_risk_parity(returns: np.ndarray, max_w: float, iters: int = 200) -> np.ndarray:
    """等风险贡献（CCR 迭代 + 单只上限投影）。"""
    n = returns.shape[1]
    cov = np.cov(returns, rowvar=False) + np.eye(n) * 1e-9
    w = np.full(n, 1.0 / n)
    for _ in range(iters):
        sigma = np.sqrt(np.diag(cov))
        contrib = w * (cov @ w)
        target = np.mean(contrib)
        w = w * (target / np.maximum(contrib, 1e-12))
        w = _project(w, max_w)
    return _project(w, max_w)


def _project(w: np.ndarray, max_w: float) -> np.ndarray:
    """单只上限投影：截断 + 归一化，多轮至稳定。"""
    for _ in range(8):
        w = np.minimum(w, max_w)
        s = w.sum()
        if s <= 0:
            return np.full_like(w, 1.0 / w.shape[0])
        w = w / s
        if (w <= max_w + 1e-9).all():
            break
    return w


def _np_hrp(returns: np.ndarray, max_w: float) -> np.ndarray:
    """层次风险平价（scipy 聚类 + 递归二分）。"""
    from scipy.cluster.hierarchy import linkage, leaves_list
    n = returns.shape[1]
    cov = np.cov(returns, rowvar=False) + np.eye(n) * 1e-9
    corr = np.corrcoef(returns, rowvar=False)
    dist = np.sqrt(np.maximum(0, 1 - corr))
    try:
        link = linkage(dist[np.triu_indices(n, k=1)], method="single")
        order = leaves_list(link)
    except Exception:  # noqa: BLE001
        order = np.arange(n)

    def _recursive_bisection(idx: list[int]) -> np.ndarray:
        if len(idx) == 1:
            w = np.zeros(n)
            w[idx[0]] = 1.0
            return w
        mid = len(idx) // 2
        left, right = idx[:mid], idx[mid:]
        sub = cov[np.ix_(left, left)]
        var_l = np.sum(np.linalg.pinv(sub + np.eye(len(left)) * 1e-9) if len(left) == 1
                       else np.diag(np.linalg.inv(sub + np.eye(len(left)) * 1e-9)))
        sub_r = cov[np.ix_(right, right)]
        var_r = np.sum(np.linalg.pinv(sub_r + np.eye(len(right)) * 1e-9) if len(right) == 1
                       else np.diag(np.linalg.inv(sub_r + np.eye(len(right)) * 1e-9)))
        alpha = var_l / (var_l + var_r) if (var_l + var_r) > 0 else 0.5
        w = np.zeros(n)
        w += alpha * _recursive_bisection(left)
        w += (1 - alpha) * _recursive_bisection(right)
        return w

    w = _recursive_bisection(list(map(int, order)))
    return _project(w, max_w)


# ---------------------------------------------------------------------------
# skfolio 适配（已安装时优先）
# ---------------------------------------------------------------------------

def _sk_optimize(returns: pd.DataFrame, method: str, max_w: float, rf: float) -> dict:
    from skfolio.optimization import MeanRisk, RiskBudgeting, HierarchicalRiskParity
    from skfolio.prior import EmpiricalPrior

    if method == "mv":
        model = MeanRisk(risk_measure="variance", objective_function="max_utility",
                         risk_free_rate=rf, max_weights=max_w,
                         portfolio_params=dict(name="MV"))
    elif method == "rp":
        model = RiskBudgeting(risk_measure="variance", risk_budget=None,
                              max_weights=max_w, portfolio_params=dict(name="RP"))
    else:
        model = HierarchicalRiskParity(max_weights=max_w,
                                       portfolio_params=dict(name="HRP"))
    try:
        model.fit(returns)
    except Exception as e:  # noqa: BLE001
        log.warning("skfolio 拟合失败 %s: %s", method, e)
        return {}
    w = model.weights_
    p = model.portfolio_
    return {
        "weights": {c: float(w[i]) for i, c in enumerate(returns.columns)},
        "expected_return": float(getattr(p, "mean", 0.0)),
        "volatility": float(getattr(p, "variance", 0.0)) ** 0.5,
        "sharpe": float(getattr(p, "sharpe_ratio", 0.0)),
        "risk_contrib": _risk_contribution(returns.values, np.asarray(w)),
        "engine": "skfolio",
    }


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def _risk_contribution(returns: np.ndarray, w: np.ndarray) -> List[float]:
    cov = np.cov(returns, rowvar=False) + np.eye(w.shape[0]) * 1e-9
    contrib = w * (cov @ w)
    total = float(np.sum(contrib))
    return [round(float(c) / total, 4) if total > 0 else 0.0 for c in contrib]


def _np_max_diversification(returns: np.ndarray, max_w: float, rf: float) -> np.ndarray:
    """最大分散化：最大化 组合加权波动 / 组合总波动（分散比率）。

    目标 D(w) = (w·σ) / sqrt(w'Σw)，σ 为各资产年化波动向量。
    用 scipy SLSQP 迭代求解，含非负 + 和=1 + 单只上限约束。
    """
    n = returns.shape[1]
    sigma = returns.std(axis=0) * np.sqrt(252) + 1e-12
    cov = np.cov(returns, rowvar=False) + np.eye(n) * 1e-9

    def _neg_d(w):
        w = np.abs(w) / (np.abs(w).sum() + 1e-12)
        num = float(w @ sigma)
        den = float(np.sqrt(w @ cov @ w)) + 1e-12
        return -(num / den)

    try:
        from scipy.optimize import minimize
        w0 = np.full(n, 1.0 / n)
        cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        bounds = [(0.0, max_w)] * n
        res = minimize(_neg_d, w0, method="SLSQP", bounds=bounds,
                       constraints=cons, options={"maxiter": 300, "ftol": 1e-10})
        w = np.abs(res.x)
        if w.sum() <= 0:
            w = np.full(n, 1.0 / n)
        w = _project(w, max_w)
    except Exception:  # noqa: BLE001
        w = np.full(n, 1.0 / n)
    return w


def _np_dr_cvar(returns: np.ndarray, max_w: float, rf: float,
                alpha: float = 0.95, rho: float = 0.5) -> np.ndarray:
    """分布鲁棒 CVaR：最小化最坏情况 95% CVaR。

    鲁棒化近似：对每只资产取历史 CVaR 与"最坏窗口 CVaR"的加权（ρ 控制鲁棒强度），
    组合目标 = 组合收益率线性映射下的鲁棒 CVaR，用 SLSQP 求最小权重。
    """
    n = returns.shape[1]
    if returns.shape[0] < 60:
        return np.full(n, 1.0 / n)

    def _cvar_col(r):
        q = np.quantile(r, 1 - alpha)
        tail = r[r <= q]
        return float(np.mean(tail)) if len(tail) else float(q)

    # 历史窗口 CVaR（每资产）+ 最坏 20% 窗口 CVaR → 鲁棒估计
    robust = []
    for j in range(n):
        col = returns[:, j]
        h_cvar = _cvar_col(col)
        wins = col.reshape(-1, 20)
        wcvar = min(_cvar_col(w) for w in wins) if wins.shape[0] > 1 else h_cvar
        robust.append(rho * h_cvar + (1 - rho) * wcvar)  # ρ 大 → 更依赖整体历史
    robust = np.array(robust)
    # 组合 CVaR 近似：用线性加权（对正态近似成立；这里作为鲁棒启发式）
    def _obj(w):
        w = np.abs(w) / (np.abs(w).sum() + 1e-12)
        return float(w @ robust) + 0.1 * float(np.sqrt(w @ (np.cov(returns, rowvar=False) + np.eye(n) * 1e-9) @ w))
    try:
        from scipy.optimize import minimize
        w0 = np.full(n, 1.0 / n)
        cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        bounds = [(0.0, max_w)] * n
        res = minimize(_obj, w0, method="SLSQP", bounds=bounds,
                       constraints=cons, options={"maxiter": 300, "ftol": 1e-10})
        w = np.abs(res.x)
        if w.sum() <= 0:
            w = np.full(n, 1.0 / n)
        w = _project(w, max_w)
    except Exception:  # noqa: BLE001
        w = np.full(n, 1.0 / n)
    return w


def optimize_portfolio(returns: pd.DataFrame, method: str = "mv",
                       max_weight: float = 0.4, risk_free_rate: float = 0.02,
                       tickers: Optional[List[str]] = None) -> dict:
    """组合优化统一入口。

    returns: DataFrame（列=标的，行=日收益率，索引=日期）
    method: mv（均值-方差）/ rp（风险平价）/ hrp（层次风险平价）/
            maxdiv（最大分散化）/ cvar（分布鲁棒 CVaR）
    返回 {ok, method, weights:{code:pct}, expected_return, volatility, sharpe,
          risk_contrib, engine, note}
    """
    if returns is None or returns.shape[1] < 2 or returns.shape[0] < 30:
        return {"ok": False, "note": f"数据不足：需≥2 标的、≥30 日收益（实际 "
                                     f"{0 if returns is None else returns.shape[1]} 标的 / "
                                     f"{0 if returns is None else returns.shape[0]} 日）"}
    ret = returns.fillna(0.0)
    cols = list(ret.columns)

    if _has_skfolio():
        try:
            out = _sk_optimize(ret, method, max_weight, risk_free_rate)
            if out:
                out["ok"] = True
                out["method"] = method
                out["note"] = "skfolio 引擎"
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("skfolio 路径失败，回退 numpy：%s", e)

    X = ret.values
    if method == "mv":
        w = _np_mean_variance(X, max_weight, risk_free_rate)
    elif method == "rp":
        w = _np_risk_parity(X, max_weight)
    elif method == "hrp":
        w = _np_hrp(X, max_weight)
    elif method == "maxdiv":
        w = _np_max_diversification(X, max_weight, risk_free_rate)
    elif method == "cvar":
        w = _np_dr_cvar(X, max_weight, risk_free_rate)
    else:
        return {"ok": False, "note": f"未知方法：{method}（可选 mv/rp/hrp/maxdiv/cvar）"}

    mu = X.mean(axis=0) * 252
    cov = np.cov(X, rowvar=False) + np.eye(X.shape[1]) * 1e-9
    vol = float(np.sqrt(w @ cov @ w * 252))
    ret_p = float(w @ mu)
    sharpe = float((ret_p - risk_free_rate) / vol) if vol > 0 else 0.0
    weights = {c: round(float(wi) * 100, 2) for c, wi in zip(cols, w)}
    return {
        "ok": True,
        "method": method,
        "weights": weights,
        "expected_return": round(ret_p * 100, 2),      # 年化 %
        "volatility": round(vol * 100, 2),             # 年化 %
        "sharpe": round(sharpe, 3),
        "risk_contrib": _risk_contribution(X, w),
        "engine": "numpy",
        "note": "numpy/scipy 内置引擎（安装 skfolio 可启用更专业的优化）",
    }


def backtest_portfolio(prices: pd.DataFrame, weights: Dict[str, float]) -> dict:
    """组合历史回测：按权重合成组合净值 → 绩效指标。"""
    if prices is None or prices.shape[0] < 2:
        return {"ok": False, "note": "价格数据不足"}
    cols = [c for c in prices.columns if c in weights]
    if not cols:
        return {"ok": False, "note": "价格与权重标的无交集"}
    w = np.array([weights[c] / 100.0 for c in cols])
    nav = prices[cols].pct_change().fillna(0.0) @ w
    nav = (1 + nav).cumprod()
    total_ret = float(nav.iloc[-1] - 1)
    years = len(nav) / 252
    annual = (nav.iloc[-1]) ** (1.0 / years) - 1.0 if years > 0 and nav.iloc[-1] > 0 else 0.0
    cummax = nav.cummax()
    dd = float((nav / cummax - 1.0).min())
    sharpe = float(nav.pct_change().dropna().mean() / nav.pct_change().dropna().std()
                   * np.sqrt(252)) if len(nav) > 2 and nav.pct_change().dropna().std() > 0 else 0.0
    return {
        "ok": True,
        "total_return_pct": round(total_ret * 100, 2),
        "annual_return_pct": round(annual * 100, 2),
        "max_drawdown_pct": round(dd * 100, 2),
        "sharpe": round(sharpe, 3),
        "bars": int(len(nav)),
        "weights_used": {c: round(float(w[i]), 4) for i, c in enumerate(cols)},
        "nav": nav,
    }


if __name__ == "__main__":
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    X = pd.DataFrame({
        "SH600519": rng.normal(0.0006, 0.012, 300),
        "SZ300750": rng.normal(0.0003, 0.02, 300),
        "AAPL": rng.normal(0.0004, 0.015, 300),
    }, index=idx)
    for m in ("mv", "rp", "hrp"):
        r = optimize_portfolio(X, method=m)
        print(m, r["engine"], r["weights"], "sharpe", r["sharpe"])
