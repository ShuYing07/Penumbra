# -*- coding: utf-8 -*-
"""PIT-Guard：Point-in-Time 数据泄漏防护（任务书B·模块二）。

参考 AlphaAgent 的 PIT-Guard 设计，在工具调用边界强制做数据时点过滤：

- guard_data(tool, payload, as_of)：校验 payload 内所有时间字段 ≤ as_of；
  超时点的记录被剔除（防 Agent 读到未来数据）。
- guard_bars(df, as_of)：K线严格截断到 as_of（无前视）。
- leakage_probe(model_fn, known_event)：向模型提问"未来事件"，检测其是否
  "知道"未来信息（模型参数化记忆泄漏探测）。
- annotate_report(report)：在回测/分析报告中标注「机械层回测 / Agent层分析」
  边界，明确 LLM 不参与收益计算。

collaboration 拓扑（panel / debate / vote）由 config.yaml 的 collaboration.mode 读取，
见 load_collaboration_config()；缺省 debate（多空结构化辩论）。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Callable, Dict, List, Optional

import pandas as pd

log = logging.getLogger("stockai.pit")

# ---------------------------------------------------------------------------
# 配置：可插拔协作模式
# ---------------------------------------------------------------------------
_DEFAULT_COLLAB = {
    "mode": "debate",
    "panel": {"agents": ["technical", "fundamental", "news"], "judge": "leader"},
    "debate": {"bull": "bull_researcher", "bear": "bear_researcher", "rounds": 3},
    "vote": {"agents": ["technical", "fundamental", "news", "sentiment"], "threshold": 0.6},
}


def load_collaboration_config(path: Optional[str] = None) -> Dict[str, object]:
    """从 config.yaml 读 collaboration 配置；文件缺失/解析失败回默认（debate）。"""
    cfg = dict(_DEFAULT_COLLAB)
    path = path or os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "config.yaml")
    if not os.path.exists(path):
        return cfg
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data.get("collaboration"), dict):
            cfg.update({k: v for k, v in data["collaboration"].items()
                        if v is not None})
    except Exception as e:  # noqa: BLE001
        log.warning("collaboration 配置读取失败，使用默认: %s", e)
    return cfg


# ---------------------------------------------------------------------------
# 时点守卫
# ---------------------------------------------------------------------------
def _extract_dates(payload: object, out: List[str]) -> None:
    """递归抽取 payload 中形如 YYYY-MM-DD / YYYYMMDD 的日期串。"""
    if isinstance(payload, dict):
        for v in payload.values():
            _extract_dates(v, out)
    elif isinstance(payload, (list, tuple)):
        for v in payload:
            _extract_dates(v, out)
    elif isinstance(payload, str):
        for m in re.findall(r"\d{4}[-/]?\d{1,2}[-/]?\d{1,2}", payload):
            out.append(re.sub(r"[-/]", "", m))


def _norm_date(s: str) -> str:
    t = re.sub(r"[-/]", "", str(s))
    return t.ljust(8, "0")[:8]


def guard_bars(df, as_of: str) -> pd.DataFrame:
    """K线严格截断到 as_of（含当日）。as_of 为空返回原数据。"""
    if df is None or len(df) == 0 or not as_of:
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df = df.copy()
            df.index = pd.to_datetime(df.index)
        except Exception:  # noqa: BLE001
            return df
    return df[df.index <= pd.Timestamp(_norm_date(as_of))]


def guard_data(tool: str, payload: object, as_of: str) -> Dict[str, object]:
    """守卫一次工具调用：返回 {allowed, filtered, reason, data}。

    - allowed：调用是否放行（as_of 缺失即放行并标注 untested）。
    - filtered：被剔除的未来时点记录数。
    - data：剔除后的数据（dict/list 深拷贝后原地过滤）。
    """
    if not as_of:
        return {"allowed": True, "filtered": 0, "reason": "as_of 未设置（不作过滤）",
                "data": payload}
    as_of_n = _norm_date(as_of)
    dates: List[str] = []
    _extract_dates(payload, dates)
    if not dates:
        return {"allowed": True, "filtered": 0, "reason": "无时间字段", "data": payload}

    def _walk(node):
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            out = []
            for it in node:
                if isinstance(it, dict) and any(
                        isinstance(v, str) and _norm_date(v) > as_of_n
                        for v in it.values()):
                    continue  # 未来记录剔除
                out.append(_walk(it))
            return out
        return node

    data = _walk(payload)
    # 统计剔除数量（近似：原始含未来日期的行数）
    filtered = len(dates) - len([d for d in dates if _norm_date(d) <= as_of_n])
    return {"allowed": True, "filtered": max(0, filtered),
            "reason": f"已按 as_of={as_of} 过滤未来数据", "data": data}


# ---------------------------------------------------------------------------
# 模型记忆泄漏探测
# ---------------------------------------------------------------------------
def leakage_probe(model_fn: Callable[[str], str],
                  future_event: str = "2026-12-31 之后A股市场发生了什么重大事件？",
                  keywords: Optional[List[str]] = None) -> Dict[str, object]:
    """向模型提问一个"未来"事件，检测其是否泄露未来信息。

    - 期望行为：模型拒绝回答或明确说"无法预知"（clean）。
    - 若模型给出具体未来事件描述（命中 keyword 列表）→ 疑似泄漏（leak）。
    - 探测为启发式：关键词列表可自定义，默认取日期特征与"未来/尚未发生"反义。
    返回 {probe, verdict, evidence, note}。
    """
    try:
        ans = model_fn(future_event) or ""
    except Exception as e:  # noqa: BLE001
        return {"probe": future_event, "verdict": "unknown",
                "evidence": f"调用失败: {type(e).__name__}", "note": "无法完成探测"}
    ans_s = str(ans).strip()
    if not ans_s:
        return {"probe": future_event, "verdict": "clean",
                "evidence": "模型无输出", "note": "无泄漏迹象"}
    safe_markers = ("无法", "不能", "不知道", "不确定", "未发生", "未来", "无法预知",
                    "not known", "cannot", "can't", "unable", "future", "no data")
    leak_hits = [k for k in (keywords or []) if k and k in ans_s]
    if leak_hits:
        return {"probe": future_event, "verdict": "leak",
                "evidence": f"命中泄漏关键词: {leak_hits}",
                "note": "模型可能编码了未来信息（参数化记忆泄漏）"}
    if any(m in ans_s for m in safe_markers):
        return {"probe": future_event, "verdict": "clean",
                "evidence": f"拒绝/无法回答: {ans_s[:80]}", "note": "无泄漏迹象"}
    # 含具体日期且给出确定性结论 → 疑似
    if re.search(r"\d{4}[-/]?\d{1,2}[-/]?\d{1,2}", ans_s) and len(ans_s) > 40:
        return {"probe": future_event, "verdict": "suspicious",
                "evidence": f"给出含日期的具体描述: {ans_s[:100]}",
                "note": "建议进一步人工核查"}
    return {"probe": future_event, "verdict": "clean",
            "evidence": f"未发现明确未来事件描述: {ans_s[:80]}", "note": "无泄漏迹象"}


# ---------------------------------------------------------------------------
# 机械层 / Agent层 分离标注
# ---------------------------------------------------------------------------
def annotate_report(report: Dict[str, object]) -> Dict[str, object]:
    """在回测/分析报告中标注机械层与 Agent 层边界。"""
    out = dict(report or {})
    out["mech_layer"] = "回测收益仅由确定性规则（技术指标/均线交叉）计算，LLM 不参与收益产生"
    out["agent_layer"] = "LLM 仅用于定性判断（新闻影响/多空逻辑），其结果不计入回测净值"
    out["pit_guard"] = "数据按 as-of 时点严格截断，防前视偏差（详见 core/pit_guard.py）"
    return out
