# -*- coding: utf-8 -*-
"""投研成果 Skill 化（2026-10 翻新 · 模块八升级版）。

参考东吴证券「投研成果 Skill 化」实践与 FinceptTerminal 工具封装思路，
把三项核心投研能力封装为**可调用 Skill**，每个 Skill 满足四要素：

1. **明确输入**：JSON Schema 风格的输入声明 + 校验（缺参/错型直接报错）；
2. **稳定执行**：确定性规则实现，不依赖 LLM，可复现、可单测；
3. **可解释输出**：每个结论附理由与关键证据数值；
4. **过程留痕**：每次调用写入 SQLite（research_skill_traces），
   含输入/输出/耗时/版本，支持审计与回放（研究过程版本化、可追溯）。

三大 Skill：
- factor_iteration   选股因子迭代：多周期动量/波动/量能因子 +
  样本内 IC 评估选出当期最优因子组合（标注样本内属性，实盘前需走
  audit_rules8 八条审计）；
- kline_pattern_search  K 线形态检索：10 种经典形态确定性识别，
  输出命中日期/强度/解释；
- deep_research      深度研究框架：五段式研究脚手架（概况→财务→
  估值→风险→结论），确定性部分直接计算，LLM 叙述层可插拔。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from core.config import DATA_DIR

log = logging.getLogger("stockai.research_skills")

SKILL_VERSION = "1.0.0"
_TRACE_DB = DATA_DIR / "research_skill_traces.db"
_TRACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_skill_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    skill TEXT NOT NULL,
    version TEXT NOT NULL,
    inputs TEXT NOT NULL,
    outputs TEXT NOT NULL,
    duration_ms REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trace_skill ON research_skill_traces(skill, ts);
"""


# ---------------------------------------------------------------------------
# 过程留痕
# ---------------------------------------------------------------------------

def _trace_conn() -> sqlite3.Connection:
    _TRACE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_TRACE_DB, timeout=10)
    con.executescript(_TRACE_SCHEMA)
    return con


def record_trace(skill: str, inputs: dict, outputs: dict,
                 duration_ms: float) -> int:
    """写入调用留痕，返回 trace_id。"""
    def _safe(obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, default=str)[:8000]
        except Exception:  # noqa: BLE001
            return str(obj)[:8000]

    with closing(_trace_conn()) as con:
        cur = con.execute(
            "INSERT INTO research_skill_traces"
            "(ts, skill, version, inputs, outputs, duration_ms)"
            " VALUES(?,?,?,?,?,?)",
            (time.time(), skill, SKILL_VERSION, _safe(inputs),
             _safe(outputs), duration_ms))
        con.commit()
        return int(cur.lastrowid)


def list_traces(skill: Optional[str] = None, limit: int = 50) -> List[dict]:
    """读取留痕（新→旧），供 UI「进化追踪/研究留痕」展示。"""
    sql = ("SELECT id, ts, skill, version, duration_ms, substr(inputs,1,200), "
           "substr(outputs,1,500) FROM research_skill_traces")
    args: tuple = ()
    if skill:
        sql += " WHERE skill=?"
        args = (skill,)
    sql += " ORDER BY id DESC LIMIT ?"
    args += (int(limit),)
    with closing(_trace_conn()) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Skill 基类与注册表
# ---------------------------------------------------------------------------

class SkillInputError(ValueError):
    """输入校验失败。"""


class ResearchSkill:
    """投研 Skill 基类：输入校验 → 确定性执行 → 留痕。"""

    name: str = ""
    description: str = ""
    # JSON Schema 风格：{field: {"type": str, "required": bool, "desc": str}}
    input_schema: Dict[str, Dict[str, Any]] = {}

    def validate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(inputs, dict):
            raise SkillInputError("inputs 必须是 dict")
        for field, spec in self.input_schema.items():
            if spec.get("required") and field not in inputs:
                raise SkillInputError(
                    f"缺少必填输入 `{field}`（{spec.get('desc', '')}）")
        return inputs

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        self.validate(inputs)
        out = self.execute(inputs)
        dur = (time.perf_counter() - t0) * 1000
        trace_id = record_trace(
            self.name,
            {k: (f"<{type(v).__name__}>" if isinstance(v, pd.DataFrame) else v)
             for k, v in inputs.items()}, out, dur)
        return {"skill": self.name, "version": SKILL_VERSION,
                "trace_id": trace_id, "duration_ms": round(dur, 2), **out}


# ---------------------------------------------------------------------------
# Skill 1：选股因子迭代
# ---------------------------------------------------------------------------

def _ic(series_factor: pd.Series, forward_ret: pd.Series) -> float:
    """Rank IC：因子值与未来收益的 Spearman 秩相关（样本内，研究用途）。"""
    df = pd.DataFrame({"f": series_factor, "r": forward_ret}).dropna()
    if len(df) < 10:
        return 0.0
    return float(df["f"].rank().corr(df["r"].rank()))


class FactorIterationSkill(ResearchSkill):
    name = "factor_iteration"
    description = ("选股因子迭代：多周期动量/波动/量能因子候选池，"
                   "以样本内 Rank IC 评估选出当期最优因子组合")
    input_schema = {
        "bars": {"type": "DataFrame", "required": True,
                 "desc": "OHLCV 日线（索引为日期，含 close/volume 列）"},
        "lookbacks": {"type": "list[int]", "required": False,
                      "desc": "动量候选周期，默认 [5,10,20,60]"},
        "forward_days": {"type": "int", "required": False,
                         "desc": "IC 评估的未来收益窗口，默认 5"},
    }

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        bars: pd.DataFrame = inputs["bars"]
        if "close" not in bars.columns or len(bars) < 80:
            raise SkillInputError("bars 需为含 close 列的 ≥80 根日线")
        lookbacks = [int(x) for x in inputs.get("lookbacks") or [5, 10, 20, 60]]
        fwd = int(inputs.get("forward_days") or 5)
        close = bars["close"].astype(float)
        fwd_ret = close.shift(-fwd) / close - 1.0

        candidates: List[Dict[str, Any]] = []
        for lb in lookbacks:
            if lb >= len(close) - fwd - 5:
                continue
            mom = close / close.shift(lb) - 1.0
            ic = _ic(mom, fwd_ret)
            candidates.append({"factor": f"momentum_{lb}", "kind": "动量",
                               "param": lb, "ic": round(ic, 4)})
        # 波动率因子（低波异象）：20 日滚动波动，取负号使「低波=高分」
        vol20 = close.pct_change().rolling(20).std()
        candidates.append({"factor": "low_volatility_20", "kind": "波动",
                           "param": 20,
                           "ic": round(_ic(-vol20, fwd_ret), 4)})
        # 量能因子：量比（5 日均量 / 60 日均量）
        if "volume" in bars.columns:
            v = bars["volume"].astype(float)
            vr = v.rolling(5).mean() / v.rolling(60).mean()
            candidates.append({"factor": "volume_ratio_5_60", "kind": "量能",
                               "param": 60,
                               "ic": round(_ic(vr, fwd_ret), 4)})
        if not candidates:
            raise SkillInputError("数据长度不足以评估任何候选因子")

        candidates.sort(key=lambda c: abs(c["ic"]), reverse=True)
        best = candidates[0]
        return {
            "candidates": candidates,
            "best": best,
            "explanation": (
                f"共评估 {len(candidates)} 个候选因子（未来 {fwd} 日收益 Rank IC，"
                f"样本内）。当期最优：{best['factor']}（{best['kind']}类，"
                f"IC={best['ic']:+.3f}）。IC>|0.05| 视为有边际信息含量；"
                f"注意本结果为样本内评估，仅作研究线索——进入策略前必须经 "
                f"audit_rules8 八条审计（前视/过拟合/多重检验）。"),
            "research_only": True,
        }


# ---------------------------------------------------------------------------
# Skill 2：K 线形态检索
# ---------------------------------------------------------------------------

def _body(r) -> float:
    return float(r["close"] - r["open"])


def _range(r) -> float:
    return max(float(r["high"] - r["low"]), 1e-9)


def _upper_shadow(r) -> float:
    return float(r["high"] - max(r["open"], r["close"]))


def _lower_shadow(r) -> float:
    return float(min(r["open"], r["close"]) - r["low"])


# 形态判定函数：(bars, i) -> strength(0~1) or 0；均在 i 处判定，只用 ≤i 的数据
def _p_doji(b, i):
    r = b.iloc[i]
    s = 1.0 - abs(_body(r)) / _range(r)
    return round(s, 3) if abs(_body(r)) / _range(r) <= 0.1 else 0.0


def _p_hammer(b, i):
    r = b.iloc[i]
    rng = _range(r)
    # 小实体（≤35% 全幅）+ 长下影（≥2 倍实体）+ 短上影
    if 0 < abs(_body(r)) / rng <= 0.35 \
            and _lower_shadow(r) >= 2 * abs(_body(r)) \
            and _upper_shadow(r) <= 0.3 * rng:
        return round(min(1.0, _lower_shadow(r) / rng), 3)
    return 0.0


def _p_inverted_hammer(b, i):
    r = b.iloc[i]
    rng = _range(r)
    if 0 < abs(_body(r)) / rng <= 0.35 \
            and _upper_shadow(r) >= 2 * abs(_body(r)) \
            and _lower_shadow(r) <= 0.3 * rng:
        return round(min(1.0, _upper_shadow(r) / rng), 3)
    return 0.0


def _p_bullish_engulfing(b, i):
    if i < 1:
        return 0.0
    p, c = b.iloc[i - 1], b.iloc[i]
    if _body(p) < 0 < _body(c) and c["open"] <= p["close"] and c["close"] >= p["open"]:
        return round(min(1.0, abs(_body(c)) / max(abs(_body(p)), 1e-9) / 2), 3)
    return 0.0


def _p_bearish_engulfing(b, i):
    if i < 1:
        return 0.0
    p, c = b.iloc[i - 1], b.iloc[i]
    if _body(p) > 0 > _body(c) and c["open"] >= p["close"] and c["close"] <= p["open"]:
        return round(min(1.0, abs(_body(c)) / max(abs(_body(p)), 1e-9) / 2), 3)
    return 0.0


def _p_morning_star(b, i):
    if i < 2:
        return 0.0
    a, m, c = b.iloc[i - 2], b.iloc[i - 1], b.iloc[i]
    if _body(a) < 0 and abs(_body(m)) < abs(_body(a)) * 0.4 and _body(c) > 0 \
            and c["close"] > (a["open"] + a["close"]) / 2:
        return 0.8
    return 0.0


def _p_evening_star(b, i):
    if i < 2:
        return 0.0
    a, m, c = b.iloc[i - 2], b.iloc[i - 1], b.iloc[i]
    if _body(a) > 0 and abs(_body(m)) < abs(_body(a)) * 0.4 and _body(c) < 0 \
            and c["close"] < (a["open"] + a["close"]) / 2:
        return 0.8
    return 0.0


def _p_three_white_soldiers(b, i):
    if i < 2:
        return 0.0
    rs = b.iloc[i - 2: i + 1]
    if all(_body(r) > 0 for _, r in rs.iterrows()) \
            and list(rs["close"]) == sorted(rs["close"]):
        return 0.75
    return 0.0


def _p_three_black_crows(b, i):
    if i < 2:
        return 0.0
    rs = b.iloc[i - 2: i + 1]
    if all(_body(r) < 0 for _, r in rs.iterrows()) \
            and list(rs["close"]) == sorted(rs["close"], reverse=True):
        return 0.75
    return 0.0


def _p_hanging_man(b, i):
    # 形态同锤子线，但需出现在一段上涨之后（趋势语境）
    if i < 5:
        return 0.0
    s = _p_hammer(b, i)
    if s and b["close"].iloc[i - 5: i].mean() < b["close"].iloc[i]:
        return round(s * 0.9, 3)
    return 0.0


PATTERN_LIBRARY: Dict[str, Dict[str, Any]] = {
    "doji": {"fn": _p_doji, "name": "十字星", "bias": "中性/变盘预警"},
    "hammer": {"fn": _p_hammer, "name": "锤子线", "bias": "潜在见底"},
    "inverted_hammer": {"fn": _p_inverted_hammer, "name": "倒锤线", "bias": "潜在见底"},
    "bullish_engulfing": {"fn": _p_bullish_engulfing, "name": "看涨吞没", "bias": "反转向上"},
    "bearish_engulfing": {"fn": _p_bearish_engulfing, "name": "看跌吞没", "bias": "反转向下"},
    "morning_star": {"fn": _p_morning_star, "name": "早晨之星", "bias": "底部反转"},
    "evening_star": {"fn": _p_evening_star, "name": "黄昏之星", "bias": "顶部反转"},
    "three_white_soldiers": {"fn": _p_three_white_soldiers, "name": "红三兵", "bias": "趋势延续向上"},
    "three_black_crows": {"fn": _p_three_black_crows, "name": "三只乌鸦", "bias": "趋势延续向下"},
    "hanging_man": {"fn": _p_hanging_man, "name": "上吊线", "bias": "上涨末端预警"},
}


class KlinePatternSkill(ResearchSkill):
    name = "kline_pattern_search"
    description = ("K 线形态检索：10 种经典形态确定性识别，"
                   "输出命中日期/强度/方向/解释（只用当日前数据，无前视）")
    input_schema = {
        "bars": {"type": "DataFrame", "required": True,
                 "desc": "OHLC 日线（含 open/high/low/close 列）"},
        "patterns": {"type": "list[str]", "required": False,
                     "desc": "限定检索的形态 id，默认全部 10 种"},
        "min_strength": {"type": "float", "required": False,
                         "desc": "最小形态强度（0~1），默认 0.5"},
    }

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        bars: pd.DataFrame = inputs["bars"]
        need = {"open", "high", "low", "close"}
        if not need.issubset(bars.columns) or len(bars) < 5:
            raise SkillInputError("bars 需含 open/high/low/close 列且 ≥5 根")
        ids = inputs.get("patterns") or list(PATTERN_LIBRARY)
        unknown = [p for p in ids if p not in PATTERN_LIBRARY]
        if unknown:
            raise SkillInputError(
                f"未知形态：{unknown}（可选 {list(PATTERN_LIBRARY)}）")
        min_s = float(inputs.get("min_strength") or 0.5)

        matches: List[Dict[str, Any]] = []
        for pid in ids:
            fn = PATTERN_LIBRARY[pid]["fn"]
            for i in range(len(bars)):
                s = fn(bars, i)
                if s and s >= min_s:
                    matches.append({
                        "pattern": pid,
                        "name": PATTERN_LIBRARY[pid]["name"],
                        "bias": PATTERN_LIBRARY[pid]["bias"],
                        "date": str(bars.index[i])[:10],
                        "strength": s,
                        "close": round(float(bars["close"].iloc[i]), 3),
                    })
        matches.sort(key=lambda m: m["date"])
        return {
            "matches": matches[-100:],          # 最多返回最近 100 条
            "total": len(matches),
            "explanation": (
                f"在 {len(bars)} 根 K 线上检索 {len(ids)} 种形态，"
                f"命中 {len(matches)} 次（强度≥{min_s}）。"
                f"形态识别为纯价格结构判定（仅用当日前数据，无前视偏差）；"
                f"形态仅为概率线索，不构成买卖建议。"),
        }


# ---------------------------------------------------------------------------
# Skill 3：深度研究框架
# ---------------------------------------------------------------------------

class DeepResearchSkill(ResearchSkill):
    name = "deep_research"
    description = ("深度研究框架：五段式脚手架（概况→财务→估值→风险→结论），"
                   "确定性部分直接计算，LLM 叙述层可插拔")
    input_schema = {
        "code": {"type": "str", "required": True, "desc": "标的代码（如 SH600519）"},
        "bars": {"type": "DataFrame", "required": False,
                 "desc": "OHLCV 日线（提供则计算技术/风险段）"},
        "funda": {"type": "dict", "required": False,
                  "desc": "基本面数据 dict（提供则计算财务/估值段）"},
    }

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        code = str(inputs["code"]).strip()
        if not code:
            raise SkillInputError("code 不能为空")
        bars: Optional[pd.DataFrame] = inputs.get("bars")
        funda: Optional[dict] = inputs.get("funda")

        sections: Dict[str, Any] = {}

        # 1. 概况
        sections["概况"] = {"code": code, "name": (funda or {}).get("name", ""),
                            "status": "确定性骨架已建立"}

        # 2. 财务（有 funda 时）
        if funda:
            fin = {}
            for k in ("pe", "pb", "roe", "gross_margin", "revenue_yoy",
                      "profit_yoy", "debt_ratio"):
                if funda.get(k) is not None:
                    fin[k] = funda[k]
            sections["财务"] = fin or {"status": "funda 已提供但无可识别字段"}

        # 3. 估值（PE/PB 分位粗判）
        if funda and (funda.get("pe") or funda.get("pb")):
            pe, pb = funda.get("pe"), funda.get("pb")
            notes = []
            if pe is not None:
                notes.append(f"PE={pe}：" + ("高于 50，估值偏贵" if float(pe) > 50
                                          else "低于 15，估值偏低" if float(pe) < 15
                                          else "处于常见区间"))
            if pb is not None:
                notes.append(f"PB={pb}：" + ("高于 8，溢价显著" if float(pb) > 8
                                          else "低于 1.5，折价区间" if float(pb) < 1.5
                                          else "处于常见区间"))
            sections["估值"] = {"notes": notes}

        # 4. 技术与风险（有 bars 时）
        if bars is not None and "close" in bars.columns and len(bars) >= 60:
            close = bars["close"].astype(float)
            ret = close.pct_change().dropna()
            ann_vol = float(ret.std() * np.sqrt(252))
            cum = (1 + ret).cumprod()
            mdd = float((cum / cum.cummax() - 1).min())
            ma20, ma60 = close.rolling(20).mean(), close.rolling(60).mean()
            trend = ("多头排列" if ma20.iloc[-1] > ma60.iloc[-1] else "空头排列")
            sections["技术"] = {
                "trend": trend,
                "ma20": round(float(ma20.iloc[-1]), 3),
                "ma60": round(float(ma60.iloc[-1]), 3),
                "last_close": round(float(close.iloc[-1]), 3),
            }
            sections["风险"] = {
                "annual_volatility": round(ann_vol, 4),
                "max_drawdown": round(mdd, 4),
                "note": "年化波动与历史最大回撤为客观统计，非未来承诺",
            }

        # 5. 结论（确定性骨架；叙述层由 LLM 插拔补充）
        done = [k for k in ("财务", "估值", "技术", "风险") if k in sections]
        sections["结论"] = {
            "completed_sections": done,
            "missing": [k for k in ("财务", "估值", "技术", "风险") if k not in sections],
            "note": "确定性研究骨架完成；深度叙述可接入多智能体分析师团队"
                    "（core/agents）补充，结论须经 AI 评审员合规审核",
        }
        return {
            "code": code,
            "sections": sections,
            "explanation": (f"{code} 五段式深度研究骨架完成："
                            f"已计算 {len(done)} 个确定性段落"
                            f"（{', '.join(done) or '无'}）。"
                            f"本输出为数据描述，不构成投资建议。"),
        }


# ---------------------------------------------------------------------------
# 注册表与统一入口
# ---------------------------------------------------------------------------

RESEARCH_SKILLS: Dict[str, ResearchSkill] = {
    s.name: s for s in (
        FactorIterationSkill(), KlinePatternSkill(), DeepResearchSkill())
}


def list_research_skills() -> List[Dict[str, Any]]:
    """Skill 目录（slug/描述/输入声明），供命令面板/Agent 发现。"""
    return [{"name": s.name, "description": s.description,
             "inputs": {k: v.get("desc", "") for k, v in s.input_schema.items()},
             "version": SKILL_VERSION}
            for s in RESEARCH_SKILLS.values()]


def run_skill(name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """统一调用入口：校验 → 执行 → 留痕。"""
    skill = RESEARCH_SKILLS.get(name)
    if skill is None:
        raise SkillInputError(f"未知 Skill：{name}（可选 {list(RESEARCH_SKILLS)}）")
    return skill.run(inputs)


if __name__ == "__main__":
    rng = np.random.default_rng(5)
    n = 200
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0008, 0.02, n)), index=idx)
    open_ = close * (1 + rng.normal(0, 0.005, n))
    high = pd.Series(np.maximum(open_, close) * 1.008, index=idx)
    low = pd.Series(np.minimum(open_, close) * 0.992, index=idx)
    bars = pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close,
                         "volume": rng.integers(1e5, 1e6, n).astype(float)},
                        index=idx)

    r1 = run_skill("factor_iteration", {"bars": bars})
    assert r1["best"]["factor"] and r1["trace_id"] > 0
    print("factor_iteration:", r1["best"], f"({r1['duration_ms']}ms)")

    r2 = run_skill("kline_pattern_search", {"bars": bars, "min_strength": 0.5})
    print("kline_pattern_search:", r2["total"], "次命中")
    assert r2["trace_id"] > 0

    r3 = run_skill("deep_research", {
        "code": "SH600519", "bars": bars,
        "funda": {"name": "贵州茅台", "pe": 28.0, "pb": 9.5, "roe": 0.31}})
    assert "技术" in r3["sections"] and "估值" in r3["sections"]
    print("deep_research:", r3["sections"]["结论"]["completed_sections"])

    traces = list_traces(limit=5)
    assert len(traces) >= 3
    print(f"留痕 {len(traces)} 条，最新 skill={traces[0]['skill']}")
    print("research_skills self-check ok")
