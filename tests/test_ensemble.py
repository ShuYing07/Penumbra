# -*- coding: utf-8 -*-
"""core.quant.ensemble 量化综合分融合单测。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.quant.ensemble import quantitative_score

P = 0


def check(name, cond, detail=""):
    global P
    assert cond, f"FAIL {name} {detail}"
    print("PASS", name)
    P += 1


def main():
    global P
    P = 0
    # 1. 两者都有 → 0~100
    r = quantitative_score({"composite": 70}, {"up_prob": 0.8}, {"regime": "bull"})
    check("both_score_range", 0 <= r["score"] <= 100, r["score"])
    check("both_verdict", "程序量化" in r["verdict"])

    # 2. 只有 factors → 退化
    r2 = quantitative_score({"composite": 40}, {}, {"regime": "bear"})
    check("only_factors", r2["score"] is not None, r2)

    # 3. 都没有 → None
    r3 = quantitative_score({}, {}, {})
    check("none_score_none", r3["score"] is None)

    # 4. 熊市降权：高分组在熊市被拉向50
    bull = quantitative_score({"composite": 80}, {"up_prob": 0.9}, {"regime": "bull"})["score"]
    bear = quantitative_score({"composite": 80}, {"up_prob": 0.9}, {"regime": "bear"})["score"]
    check("bear_pulls_to_neutral", bear < bull, f"bull={bull} bear={bear}")

    # 5. basis 含 ML
    check("basis_has_ml", any("ML" in b for b in quantitative_score(
        {"composite": 60}, {"up_prob": 0.7, "signal": "ML偏多"}, {})["basis"]))

    # 6. 强空
    r6 = quantitative_score({"composite": 10}, {"up_prob": 0.1}, {"regime": "bear"})
    check("strong_bear", "看空" in r6["verdict"], r6["verdict"])

    print(f"{P}/{P} 个融合测试通过")
    assert P == 7


if __name__ == "__main__":
    main()
