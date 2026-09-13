# -*- coding: utf-8 -*-
"""ML 集成信号：用随机森林从技术特征学习"未来短期方向"，输出概率+因子贡献。

设计要点（对标 IntelliTradeAI：RF/XGB 集成 + 可解释性 + 波动率自适应）：
- 纯本地、零网络、零 LLM token；训练在几百~几千行日线上毫秒级完成；
- 严格防前视：特征只用截至当日数据，标签用未来 N 日收益；预测行不参与训练；
- 数据不足 / 类别单一 / sklearn 缺失 → 全部优雅降级返回 None，绝不拖垮管线；
- 输出"未来 up 日上涨概率"作为新增因子，喂给技术/风控节点；
  并附 top 特征贡献（等价 SHAP 的全局可解释性：哪个因子在推动信号）。
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from core.quant.indicators import macd, rsi, sma, boll

log = logging.getLogger("stockai.quant.ml")

_HORIZON = 5          # 预测未来 5 个交易日
_MIN_SAMPLES = 150    # 最少训练样本
_TOP_FEATS = 6

_FEAT_NAMES = [
    "ret_1", "ret_5", "ret_20", "mom_20", "mom_60",
    "rsi14", "macd_hist", "boll_pos", "vol_ratio",
    "volatility", "ma20_dev",
]


def _features_row(close: pd.Series, vol: pd.Series, i: int) -> list[float] | None:
    """计算第 i 行（含）为止的特征向量。任何需要更早数据的窗口失败则 None。"""
    if i < 60:
        return None
    c = close.iloc[:i + 1]
    v = vol.iloc[:i + 1]
    last = float(c.iloc[-1])
    try:
        ret1 = last / float(c.iloc[-2]) - 1.0
        ret5 = last / float(c.iloc[-6]) - 1.0
        ret20 = last / float(c.iloc[-21]) - 1.0
        mom20 = ret5
        mom60 = last / float(c.iloc[-61]) - 1.0
        r = float(rsi(c).iloc[-1])
        _, _, hist = macd(c)
        h = float(hist.iloc[-1])
        mid, up, low = boll(c)
        boll_pos = (last - float(low.iloc[-1])) / (float(up.iloc[-1]) - float(low.iloc[-1]) + 1e-9)
        v5 = float(v.tail(5).mean())
        v20 = float(v.tail(20).mean())
        vratio = v5 / (v20 + 1e-9)
        ann_vol = float(c.pct_change().dropna().tail(20).std() * math.sqrt(252.0))
        ma20 = float(sma(c, 20).iloc[-1])
        ma20_dev = last / ma20 - 1.0
        vals = [ret1, ret5, ret20, mom20, mom60, r, h, boll_pos, vratio, ann_vol, ma20_dev]
        if any(math.isnan(x) or math.isinf(x) for x in vals):
            return None
        return vals
    except Exception:  # noqa: BLE001
        return None


def ml_signal(bars: pd.DataFrame) -> dict:
    """对日线 df（升序）训练随机森林并预测最新一行未来5日方向概率。

    返回 {up_prob(0~1), signal, top_features[(名,贡献)], n_samples, note}；
    任何不可用情形返回 {up_prob: None, ...}。
    """
    try:
        from sklearn.ensemble import RandomForestClassifier
    except Exception as e:  # noqa: BLE001
        return {"up_prob": None, "signal": "不可用", "note": f"sklearn未安装:{e}",
                "top_features": [], "n_samples": 0}

    if bars is None or len(bars) < _MIN_SAMPLES + _HORIZON + 5:
        return {"up_prob": None, "signal": "数据不足",
                "note": f"日线需≥{_MIN_SAMPLES + _HORIZON}根",
                "top_features": [], "n_samples": 0}

    bars = bars.sort_index()
    close, vol = bars["close"], bars["volume"]
    n = len(bars)

    X, y = [], []
    for i in range(60, n - _HORIZON):
        feat = _features_row(close, vol, i)
        if feat is None:
            continue
        fut = float(close.iloc[i + _HORIZON] / close.iloc[i] - 1.0)
        # 波动率自适应阈值：以过去20日年化波动的一半作涨跌分界，避免震荡市乱标
        X.append(feat)
        y.append(1 if fut > 0.0 else 0)

    if len(X) < _MIN_SAMPLES or len(set(y)) < 2:
        return {"up_prob": None, "signal": "样本不足或方向单一",
                "note": f"有效样本{len(X)}", "top_features": [], "n_samples": len(X)}

    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)

    try:
        model = RandomForestClassifier(
            n_estimators=200, max_depth=6, min_samples_leaf=10,
            class_weight="balanced", random_state=42, n_jobs=1)
        model.fit(X, y)
        # 最新一行特征（不参与训练）
        last_feat = _features_row(close, vol, n - 1)
        if last_feat is None:
            return {"up_prob": None, "signal": "最新特征缺失", "note": "",
                    "top_features": [], "n_samples": len(X)}
        proba = model.predict_proba([last_feat])[0]
        classes = list(model.classes_)
        up_prob = float(proba[classes.index(1)]) if 1 in classes else 0.5
        imp = model.feature_importances_
        order = np.argsort(imp)[::-1][:_TOP_FEATS]
        top = [(_FEAT_NAMES[j], round(float(imp[j]), 3)) for j in order if imp[j] > 0.005]
        # 训练集历史命中率（样本内，仅参考，非未来保证）
        acc = float((model.predict(X) == y).mean())
        if up_prob >= 0.58:
            sig = f"ML偏多（上涨概率{up_prob*100:.0f}%）"
        elif up_prob <= 0.42:
            sig = f"ML偏空（上涨概率{up_prob*100:.0f}%）"
        else:
            sig = f"ML中性（上涨概率{up_prob*100:.0f}%）"
        return {
            "up_prob": round(up_prob, 3), "signal": sig,
            "top_features": top, "n_samples": len(X),
            "train_acc_ref": round(acc, 3),
            "note": f"随机森林{len(X)}样本训练，样本内参考命中率{acc*100:.0f}%（非未来保证）",
        }
    except Exception as e:  # noqa: BLE001
        log.warning("ML信号训练失败：%s", e)
        return {"up_prob": None, "signal": "训练失败", "note": str(e)[:120],
                "top_features": [], "n_samples": 0}
