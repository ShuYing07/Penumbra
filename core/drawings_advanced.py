# -*- coding: utf-8 -*-
"""高级绘图工具计算（模块六 · 参考 VNInvestCharts 76 工具子集）。

纯数学函数，输出绘图所需关键点/角度/通道，供 chart_tab 渲染与 AI 引用：

- gann_angles(anchor_x, anchor_y, scale)：Gann 角度线 1x1 / 1x2 / 2x1；
- pitchfork(a, b, c)：Andrew's Pitchfork 中位线 + 上下通道（三点）；
- harmonic_abcd(a, b, c, d=None)：谐波 AB=CD 对称 + XABCD 关键位；
- elliott_projection(swing_points)：最近 5 段折返投影第 5 浪目标。

坐标约定与 drawings.py 一致：x=全局 K 线索引，y=价格。
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

Point = Dict[str, float]


def _slope(p1: Point, p2: Point) -> float:
    dx = p2["x"] - p1["x"]
    return float("inf") if abs(dx) < 1e-9 else (p2["y"] - p1["y"]) / dx


def gann_angles(anchor: Point, scale: float = 1.0,
                degrees: Optional[List[float]] = None) -> List[dict]:
    """Gann 角度线：以 anchor 为原点，按角度生成线（全局索引坐标）。

    scale：1 单位 x（一根 K 线）对应的价格步长，用于把角度换算为斜率。
    返回 [{degree, slope, x1, y1, x2, y2}]（从 anchor 向右延伸 120 根）。
    """
    degs = degrees or [45.0, 26.565, 63.435]  # 1x1 / 1x2 / 2x1
    out: List[dict] = []
    x0, y0 = anchor["x"], anchor["y"]
    for d in degs:
        rad = math.radians(d)
        slope = math.tan(rad) * scale
        x2 = x0 + 120.0
        y2 = y0 + slope * 120.0
        out.append({"degree": d, "slope": round(slope, 6),
                    "x1": x0, "y1": y0, "x2": x2, "y2": round(y2, 4)})
    return out


def pitchfork(a: Point, b: Point, c: Point) -> dict:
    """Andrew's Pitchfork：A 为锚点，B/C 定义通道。

    返回 {median: [p1, p2], upper: [p1, p2], lower: [p1, p2]}——
    中位线过 A 且平行于 B→C；上下通道平行且过 B/C。
    """
    mid_x = (b["x"] + c["x"]) / 2.0
    mid_y = (b["y"] + c["y"]) / 2.0
    slope = _slope(b, c)
    if math.isinf(slope):
        slope = 0.0
    x2 = a["x"] + 120.0
    med_p2 = {"x": x2, "y": a["y"] + slope * 120.0}
    up_p1 = {"x": b["x"], "y": b["y"]}
    up_p2 = {"x": b["x"] + 120.0, "y": b["y"] + slope * 120.0}
    lo_p1 = {"x": c["x"], "y": c["y"]}
    lo_p2 = {"x": c["x"] + 120.0, "y": c["y"] + slope * 120.0}
    return {"median": [{"x": a["x"], "y": a["y"]}, med_p2],
            "upper": [up_p1, up_p2], "lower": [lo_p1, lo_p2]}


def harmonic_abcd(a: Point, b: Point, c: Point,
                  d: Optional[Point] = None) -> dict:
    """谐波 AB=CD：给定 A/B/C，计算潜在 D 位（BC 回撤/扩展）。

    - d 省略时按经典 AB=CD：D = C + (C-B) * 1.0（对称），并给出
      0.618 / 1.272 / 1.618 三档扩展位；
    - 返回 {potential_d: {x, y}, variants: [{label, y}], valid: bool}。
    """
    if abs(b["x"] - a["x"]) < 1e-9:
        return {"potential_d": None, "variants": [], "valid": False}
    # AB 与 BC 的幅度（价格空间）
    ab_len = abs(b["y"] - a["y"])
    bc_len = abs(c["y"] - b["y"])
    if ab_len < 1e-9:
        return {"potential_d": None, "variants": [], "valid": False}
    direction = 1 if c["y"] > b["y"] else -1
    # D 的 x：对称投影（C 再平移 AB 的 x 距离）
    x_d = c["x"] + (b["x"] - a["x"])
    y_base = c["y"] + direction * bc_len
    variants = [
        {"label": "1.000 (AB=CD)", "y": c["y"] + direction * bc_len},
        {"label": "0.618 扩展", "y": c["y"] + direction * bc_len * 0.618},
        {"label": "1.272 扩展", "y": c["y"] + direction * bc_len * 1.272},
        {"label": "1.618 扩展", "y": c["y"] + direction * bc_len * 1.618},
    ]
    return {"potential_d": {"x": x_d, "y": round(y_base, 4)},
            "variants": variants, "valid": True}


def elliott_projection(swings: List[Point]) -> dict:
    """艾略特波浪投影：给定最近 5 段折返（摆动点），投影第 5 浪目标。

    返回 {target: {x, y}, waves: [{(i0,i1), type, extent}], note}。
    第 5 浪目标 = 第 3 浪端点 + 第 1 浪幅度的 0.618~1.0（斐波那契）。
    """
    if len(swings) < 4:
        return {"target": None, "waves": [], "note": "摆动点不足 4 个，无法投影"}
    # 取最后 4 点构成 3 段
    p0, p1, p2, p3 = swings[-4:]
    wave1 = abs(p1["y"] - p0["y"])
    wave3 = abs(p3["y"] - p2["y"])
    if wave1 < 1e-9:
        return {"target": None, "waves": [], "note": "第 1 浪幅度为 0"}
    direction = 1 if p1["y"] > p0["y"] else -1
    t_lo = p3["y"] + direction * wave1 * 0.618
    t_hi = p3["y"] + direction * wave1 * 1.0
    x_t = p3["x"] + (p3["x"] - p0["x"]) / 3.0
    return {"target": {"x": round(x_t, 2),
                       "y_lo": round(t_lo, 4), "y_hi": round(t_hi, 4)},
            "waves": [{"i0": p0, "i1": p1, "type": "1", "extent": round(wave1, 4)},
                      {"i0": p2, "i1": p3, "type": "3", "extent": round(wave3, 4)}],
            "note": "第5浪目标 ≈ 第3浪终点 + 第1浪幅度×[0.618, 1.0]"}


if __name__ == "__main__":
    # 自检
    g = gann_angles({"x": 100.0, "y": 320.0}, scale=1.0)
    assert len(g) == 3
    assert g[0]["degree"] == 45.0 and abs(g[0]["slope"] - 1.0) < 1e-6
    pf = pitchfork({"x": 0.0, "y": 100.0}, {"x": 30.0, "y": 110.0},
                   {"x": 60.0, "y": 90.0})
    assert len(pf["median"]) == 2 and len(pf["upper"]) == 2
    h = harmonic_abcd({"x": 0.0, "y": 100.0}, {"x": 10.0, "y": 110.0},
                      {"x": 20.0, "y": 105.0})
    assert h["valid"] and h["potential_d"] and len(h["variants"]) == 4
    e = elliott_projection([{"x": 0.0, "y": 100.0}, {"x": 10.0, "y": 120.0},
                            {"x": 20.0, "y": 110.0}, {"x": 30.0, "y": 130.0}])
    assert e["target"] and e["waves"]
    e2 = elliott_projection([{"x": 0.0, "y": 100.0}, {"x": 5.0, "y": 101.0}])
    assert e2["target"] is None
    print("drawings_advanced self-check ok "
          f"(gann={len(g)}, pitchfork=med:{len(pf['median'])}pts, "
          f"harmonic={h['potential_d']['y']}, elliott={e['target']})")
