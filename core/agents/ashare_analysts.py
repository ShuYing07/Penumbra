# -*- coding: utf-8 -*-
"""A股特色分析师团队（模块二 · 参考 marvel 9 分析师特化）。

新增 4 位 A股特化角色，全部为「确定性优先 + LLM 增强」的降级安全节点：
- policy_analyst    政策分析师：从新闻/公告中识别监管与政策信号；
- hot_money_analyst 游资分析师：量价异动（放量/封板）推断游资动向；
- unlock_analyst    解禁分析师：限售股解禁监控（数据源缺失时降级提示）；
- volume_price_analyst 量价分析师：量价关系规则化（放量上涨/缩量回调等）。

每个节点返回 {signals: {key: {stance, confidence, view, key_points, risks}}}，
缺数据时输出低置信度中性信号——会被团队质量门控（quality_gate）自动剔除。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("stockai.agents.ashare")

# 政策关键词 → 方向（利好/利空/中性）
_POLICY_KEYWORDS: list[tuple[list[str], str]] = [
    (["降准", "降息", "减税", "补贴", "扶持", "产业政策", "专项资金",
      "放宽", "支持", "利好"], "利好"),
    (["监管", "处罚", "立案", "调查", "收紧", "限制", "规范", "整顿",
      "风险提示"], "利空"),
    (["政策", "会议", "部署", "规划"], "中性"),
]


def _bars_df(state: Dict[str, object]):
    """从 state 取 K 线 DataFrame（各节点共用）。"""
    d = state.get("data") or {}
    bars = d.get("bars")
    if bars is None:
        bars = d.get("df")
    return bars


# ---------------------------------------------------------------------------
# 1. 政策分析师
# ---------------------------------------------------------------------------
def policy_analyst(state: Dict[str, object], runner=None) -> Dict[str, object]:
    """识别新闻/公告中的政策信号，输出政策面观点。"""
    texts: List[str] = []
    news = state.get("news")
    if isinstance(news, list):
        for n in news:
            if isinstance(n, dict):
                texts.append(str(n.get("title") or n.get("content") or ""))
    hits: list[str] = []
    direction = "中性"
    for kw, d in _POLICY_KEYWORDS:
        for t in texts:
            if any(k in t for k in kw):
                hits.append(f"{kw[0]}→{d}")
                if direction == "中性":
                    direction = d
                elif d != "中性" and d != direction:
                    direction = "中性"
    if not hits:
        return {"signals": {"policy": {
            "stance": "中性", "confidence": 0.2,
            "view": "无显著政策信号（数据源受限）",
            "key_points": ["未识别到监管/产业政策相关资讯"], "risks": []}}}
    return {"signals": {"policy": {
        "stance": "看多" if direction == "利好" else ("看空" if direction == "利空" else "中性"),
        "confidence": 0.55, "view": f"政策面{_direction_cn(direction)}",
        "key_points": hits[:5], "risks": ["政策落地节奏不确定"]}}}


def _direction_cn(d: str) -> str:
    return {"利好": "利好", "利空": "利空", "中性": "中性"}[d]


# ---------------------------------------------------------------------------
# 2. 游资分析师（龙虎榜/封板数据源缺失时用量价异动推断）
# ---------------------------------------------------------------------------
def hot_money_analyst(state: Dict[str, object], runner=None) -> Dict[str, object]:
    """游资动向：优先龙虎榜（数据源缺失降级），回退量价异动规则。"""
    bars = _bars_df(state)
    key_points: list[str] = []
    if bars is not None and len(bars) >= 5:
        try:
            close = bars["close"].astype(float)
            vol = bars["volume"].astype(float)
            last = close.iloc[-1]
            prev = close.iloc[-2]
            vol_ratio = float(vol.iloc[-1] / max(vol.iloc[-5:].mean(), 1e-9))
            chg = float(last / prev - 1)
            if chg >= 0.095 and vol_ratio >= 2.0:
                key_points.append(f"近涨停放量（+{chg:.1%}，量比{vol_ratio:.1f}），疑似游资抢筹")
            elif chg <= -0.05 and vol_ratio >= 2.0:
                key_points.append(f"放量下跌（{chg:.1%}，量比{vol_ratio:.1f}），警惕资金出逃")
            elif vol_ratio <= 0.6:
                key_points.append(f"缩量（量比{vol_ratio:.1f}），交投清淡")
            else:
                key_points.append(f"量价平稳（日涨幅{chg:.1%}，量比{vol_ratio:.1f}）")
        except Exception as e:  # noqa: BLE001
            key_points.append(f"量价计算失败：{e}")
    if not key_points:
        return {"signals": {"hot_money": {
            "stance": "中性", "confidence": 0.2,
            "view": "龙虎榜数据不可用，无游资信号",
            "key_points": ["缺少龙虎榜/封板数据源"], "risks": []}}}
    return {"signals": {"hot_money": {
        "stance": "看多" if any("抢筹" in k for k in key_points) else
                  ("看空" if any("出逃" in k for k in key_points) else "中性"),
        "confidence": 0.45, "view": "游资/资金面：量价异动规则推断",
        "key_points": key_points[:4],
        "risks": ["规则推断，非龙虎榜实证数据"]}}}


# ---------------------------------------------------------------------------
# 3. 解禁分析师
# ---------------------------------------------------------------------------
def unlock_analyst(state: Dict[str, object], runner=None) -> Dict[str, object]:
    """限售股解禁监控。数据源缺失时给出中性降级提示。"""
    return {"signals": {"unlock": {
        "stance": "中性", "confidence": 0.2,
        "view": "解禁数据源不可用（可配置东财/同花顺解禁接口）",
        "key_points": ["建议关注 60/90/180 天解禁日历"], "risks": ["若存在大额解禁需警惕抛压"]}}}


# ---------------------------------------------------------------------------
# 4. 量价分析师
# ---------------------------------------------------------------------------
def volume_price_analyst(state: Dict[str, object], runner=None) -> Dict[str, object]:
    """量价关系规则化：放量上涨/放量下跌/缩量回调/量价背离。"""
    bars = _bars_df(state)
    if bars is None or len(bars) < 10:
        return {"signals": {"volume_price": {
            "stance": "中性", "confidence": 0.2,
            "view": "K线数据不足，无法量价分析",
            "key_points": [], "risks": []}}}
    try:
        close = bars["close"].astype(float)
        vol = bars["volume"].astype(float)
        c5, c1 = close.iloc[-5], close.iloc[-1]
        v5 = float(vol.iloc[-5:].mean())
        v1 = float(vol.iloc[-1])
        ret5 = float(c1 / c5 - 1)
        ratio = v1 / max(v5, 1e-9)
        if ret5 >= 0.05 and ratio >= 1.5:
            stance, pts, risk = "看多", ["放量上攻：5日涨 %.1f%%、量比 %.1f" % (ret5 * 100, ratio)], []
        elif ret5 <= -0.05 and ratio >= 1.5:
            stance, pts, risk = "看空", ["放量下跌：5日跌 %.1f%%、量比 %.1f" % (ret5 * 100, ratio)], ["量价同跌，抛压未释放"]
        elif ret5 >= 0.02 and ratio <= 0.7:
            stance, pts, risk = "看多", ["缩量上涨：量比 %.1f，浮筹锁定" % ratio], []
        elif ret5 <= -0.02 and ratio <= 0.7:
            stance, pts, risk = "中性", ["缩量回调：量比 %.1f，抛压有限" % ratio], []
        else:
            stance, pts, risk = "中性", ["量价平稳：5日涨 %.1f%%、量比 %.1f" % (ret5 * 100, ratio)], []
        return {"signals": {"volume_price": {
            "stance": stance, "confidence": 0.5, "view": "量价关系：%s" % pts[0],
            "key_points": pts, "risks": risk}}}
    except Exception as e:  # noqa: BLE001
        return {"signals": {"volume_price": {
            "stance": "中性", "confidence": 0.2,
            "view": f"量价计算失败：{e}", "key_points": [], "risks": []}}}


ASHARE_KEYS = ["policy", "hot_money", "unlock", "volume_price"]
_ASHARE_FNS = {"policy": policy_analyst, "hot_money": hot_money_analyst,
               "unlock": unlock_analyst, "volume_price": volume_price_analyst}


def run_ashare_group(state: Dict[str, object], runner=None,
                     max_workers: int = 4) -> Dict[str, object]:
    """并行执行 A股特色分析师，结果并入 state["signals"]。"""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_ASHARE_FNS[k], dict(state), runner): k
                for k in ASHARE_KEYS}
        for fut in futs:
            key = futs[fut]
            try:
                delta = fut.result()
                state.setdefault("signals", {}).update(delta.get("signals", {}))
            except Exception as e:  # noqa: BLE001
                log.warning("A股分析师 %s 失败: %s", key, e)
    return state


if __name__ == "__main__":
    import pandas as pd
    import numpy as np
    # 自检：量价/游资（合成 K 线）
    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.015, 30)))
    bars = pd.DataFrame({"close": close,
                         "volume": np.r_[rng.integers(1e5, 3e5, 25),
                                          rng.integers(1e5, 3e5, 4), [6e5]]})
    st = {"data": {"bars": bars}, "news": [{"title": "央行宣布降准0.5个百分点"}]}
    r1 = run_ashare_group(dict(st))
    assert "policy" in r1["signals"] and "volume_price" in r1["signals"]
    assert r1["signals"]["policy"]["stance"] == "看多"
    assert r1["signals"]["volume_price"]["stance"] in ("看多", "看空", "中性")
    assert "hot_money" in r1["signals"] and "unlock" in r1["signals"]
    print("ashare_analysts self-check ok")
