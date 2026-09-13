# -*- coding: utf-8 -*-
"""盯盘条件解析引擎 + 评估引擎（纯本地，不调 LLM）。

支持五类语法模板：
  价格：现价跌破/突破/大于/小于 MA5/MA10/MA20/MA60，或 现价大于 N元
  涨跌幅：涨幅/跌幅/涨跌 超过/大于/小于 N%
  RSI：RSI 大于/小于 N
  MACD：MACD 金叉/死叉
  成交量：成交量放大 N倍 / 缩量

设计要点：
- 解析失败返回带 error 的 Condition（不抛异常）；评估任何异常都吞掉返回 ❌无效，
  绝不外抛拖垮整轮扫描。
- 规则确定性、可复现、零成本，符合项目"数字程序算好、LLM 只解读"纪律。
- "跌破/突破"=穿透（前在上方/下方，现穿过）；"大于/小于"=状态比较。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_GRAMMAR_HINT = (
    "支持语法：现价跌破/突破MA5/MA20、涨幅超过N%、"
    "RSI大于N、MACD金叉/死叉、成交量放大N倍"
)

# ---------- 归一化 ----------
_FULL2HALF = str.maketrans("０１２３４５６７８９％", "0123456789%")
_CN_DIGIT = {"零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
             "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}


def _cn_digits(t: str) -> str:
    """中文数字→阿拉伯（单字 + 十的组合：七→7、十→10、二十→20、二十三→23）。"""
    def rep(m: re.Match) -> str:
        s = m.group(0)
        if "十" in s:
            a, _, b = s.partition("十")
            tens = _CN_DIGIT.get(a, "1") if a else "1"
            ones = _CN_DIGIT.get(b, "0") if b else "0"
            return str(int(tens) * 10 + int(ones))
        return "".join(_CN_DIGIT.get(c, c) for c in s)
    return re.sub(r"[一二两三四五六七八九十]+", rep, t)


def normalize(text: str) -> str:
    """全角→半角、中文数字→阿拉伯、去空格、小写。"""
    t = (text or "").strip().lower()
    t = t.translate(_FULL2HALF)
    t = _cn_digits(t)
    t = re.sub(r"\s+", "", t)
    return t


# ---------- 数据结构 ----------
@dataclass
class Condition:
    kind: str | None            # price / chgpct / rsi / macd / volume / None
    field: str = ""             # MA20 / price / chg_pct / rsi14 / macd_signal / vol_ratio
    op: str | None = None       # gt / lt / cross_up / cross_down / eq
    value: float | str | None = None
    direction: str = ""        # up / down / either（仅 chgpct 用）
    raw: str = ""
    error: str | None = None


@dataclass
class TriggerResult:
    triggered: bool
    distance: str
    status: str                 # ✅触发 / ⏳等待 / ❌无效 / —无数据


# ---------- 算符 ----------
_GT = {"大于", "超过", "高于", "高过", "≥", ">=", ">"}
_LT = {"小于", "低于", "不到", "≤", "<=", "<"}
_OP_PAT = r"(大于|超过|高于|高过|小于|低于|不到|≥|>=|>|≤|<=|<)"


def _op(word: str) -> str | None:
    if word in _GT:
        return "gt"
    if word in _LT:
        return "lt"
    return None


# ---------- 各类正则（fullmatch，按特异性排序）----------
_RE_MACD = re.compile(r"macd(金叉|死叉)")
_RE_RSI = re.compile(r"rsi" + _OP_PAT + r"(\d+(?:\.\d+)?)")
_RE_CHGPCT = re.compile(r"(涨幅|跌幅|涨跌)" + _OP_PAT + r"(\d+(?:\.\d+)?)%")
_RE_VOL = re.compile(r"成交量(放大|缩量)(\d+(?:\.\d+)?)?倍?")
_RE_PRICE_VAL = re.compile(r"(?:现价|价格|股价)" + _OP_PAT + r"(\d+(?:\.\d+)?)元")
_RE_PRICE_MA = re.compile(
    r"(?:现价|价格|股价)?(跌破|突破|大于|超过|高于|高过|小于|低于|不到|≥|>=|>|≤|<=|<)"
    r"(?:ma(?P<n1>\d+)|(?P<n2>\d+)(?:日[均线]*|均线))"
)

_CN2DIRE = {"涨幅": "up", "跌幅": "down", "涨跌": "either"}


def parse(text: str) -> Condition:
    """把自然语言条件解析成 Condition；无法识别时返回带 error 的 Condition。"""
    raw = (text or "").strip()
    t = normalize(raw)
    t = re.sub(r"(提醒|通知|报警|警报|的时候|时)$", "", t)
    if not t:
        return Condition(kind=None, error="条件为空。" + _GRAMMAR_HINT, raw=raw)

    m = _RE_MACD.fullmatch(t)
    if m:
        want = "MACD金叉" if m.group(1) == "金叉" else "MACD死叉"
        return Condition("macd", "macd_signal", "eq", value=want, raw=raw)

    m = _RE_RSI.fullmatch(t)
    if m:
        return Condition("rsi", "rsi14", _op(m.group(1)), float(m.group(2)), raw=raw)

    m = _RE_CHGPCT.fullmatch(t)
    if m:
        return Condition("chgpct", "chg_pct", _op(m.group(2)), float(m.group(3)),
                         direction=_CN2DIRE[m.group(1)], raw=raw)

    m = _RE_VOL.fullmatch(t)
    if m:
        kv, n = m.group(1), m.group(2)
        if kv == "放大":
            return Condition("volume", "vol_ratio", "gt", float(n) if n else 1.5, raw=raw)
        return Condition("volume", "vol_ratio", "lt", 1.0, raw=raw)

    m = _RE_PRICE_VAL.fullmatch(t)
    if m:
        return Condition("price", "price", _op(m.group(1)), float(m.group(2)), raw=raw)

    m = _RE_PRICE_MA.fullmatch(t)
    if m:
        word = m.group(1)
        n = int(m.group("n1") or m.group("n2"))
        if word == "跌破":
            op = "cross_down"
        elif word == "突破":
            op = "cross_up"
        else:
            op = _op(word) or "gt"
        return Condition("price", f"MA{n}", op, value=None, raw=raw)

    return Condition(kind=None, error="无法识别。" + _GRAMMAR_HINT, raw=raw)


def preview(text: str) -> str:
    """UI「测试条件」用：返回可读的解析结果。"""
    c = parse(text)
    if c.error:
        return f"❌ {c.error}"
    parts = [f"类型={c.kind}", f"字段={c.field}", f"比较={c.op}", f"阈值={c.value}"]
    if c.direction:
        parts.append(f"方向={c.direction}")
    return "✅ " + " | ".join(parts)


def _cmp(cur: float, op: str | None, thr: float, dist: str) -> TriggerResult:
    if op == "gt":
        trig = cur > thr
    elif op == "lt":
        trig = cur < thr
    else:
        trig = False
    return TriggerResult(trig, dist, "✅触发" if trig else "⏳等待")


def evaluate(cond: Condition, snapshot: dict | None, realtime: dict | None) -> TriggerResult:
    """评估条件是否触发。snapshot=latest_snapshot 输出，realtime=get_realtime 输出。"""
    if cond.error or cond.kind is None:
        return TriggerResult(False, "", "❌无效")
    snap = snapshot or {}
    rt = realtime or {}
    try:
        kind = cond.kind
        if kind == "macd":
            sig = (snap.get("macd") or {}).get("signal")
            if not sig:
                return TriggerResult(False, "无明显信号", "—无数据")
            trig = (sig == cond.value)
            return TriggerResult(trig, sig, "✅触发" if trig else "⏳等待")

        if kind == "rsi":
            cur = snap.get("rsi14")
            if cur is None:
                return TriggerResult(False, "", "—无数据")
            return _cmp(float(cur), cond.op, float(cond.value),
                        f"RSI{cur:.1f} vs {cond.value}")

        if kind == "volume":
            cur = snap.get("vol_ratio_5_20")
            if cur is None:
                return TriggerResult(False, "", "—无数据")
            return _cmp(float(cur), cond.op, float(cond.value),
                        f"量比{cur:.2f} vs {cond.value}")

        if kind == "chgpct":
            cur = rt.get("chg_pct")
            if cur is None:
                cur = snap.get("chg_pct_1d")
            if cur is None:
                return TriggerResult(False, "", "—无数据")
            cur = float(cur)
            d = cond.direction or "either"
            if d == "up":
                actual = cur
            elif d == "down":
                actual = -cur          # 跌幅 = -涨跌
            else:
                actual = abs(cur)
            return _cmp(actual, cond.op, float(cond.value),
                        f"{cur:+.2f}% vs 阈{cond.value}%")

        if kind == "price":
            cur = rt.get("price")
            if cur is None:
                cur = snap.get("close")
            if cur is None:
                return TriggerResult(False, "", "—无数据")
            cur = float(cur)
            if cond.field == "price":      # 常量价位
                return _cmp(cur, cond.op, float(cond.value),
                            f"{cur} vs {cond.value}元")
            ma = (snap.get("ma") or {}).get(cond.field)
            if ma is None:
                return TriggerResult(False, "", "—无数据")
            ma = float(ma)
            prev = snap.get("prev_close")
            dist = f"距{cond.field} {(cur / ma - 1) * 100:+.2f}%"
            op = cond.op
            if op == "cross_down":
                trig = cur < ma and (prev is not None and float(prev) >= ma)
            elif op == "cross_up":
                trig = cur > ma and (prev is not None and float(prev) <= ma)
            elif op == "gt":
                trig = cur > ma
            elif op == "lt":
                trig = cur < ma
            else:
                trig = False
            return TriggerResult(trig, dist, "✅触发" if trig else "⏳等待")
    except Exception:  # noqa: BLE001
        return TriggerResult(False, "", "❌无效")
    return TriggerResult(False, "", "❌无效")
