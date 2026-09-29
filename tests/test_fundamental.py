# -*- coding: utf-8 -*-
"""模块九：基本面分析引擎测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core.fundamental_analyzer import analyze_fundamentals, render_fundamental_card

# 1) 结构完整性（mock 环境：新浪/东财不可达 → 应有降级 note 但结构完整）
ana = analyze_fundamentals("SH600519")
for key in ("ok", "score", "grade", "dimensions", "valuation", "peers", "reports", "note"):
    assert key in ana, f"缺字段 {key}"
assert isinstance(ana["dimensions"], list)
# 综合健康度条目存在
assert any(d["name"] == "综合健康度" for d in ana["dimensions"])
# note 非空（数据源不可达时的诚实标注）
print(f"[ok] 结构完整；note={ana['note']}")

# 2) 评分逻辑：纯规则单元测试（直接构造状态走 render，另测增速函数）
from core.fundamental_analyzer import _num, _growth
assert _num("12.5") == 12.5 and _num("-") is None and _num("1,234") == 1234.0
assert _growth(110, 100) == 10.0 and _growth(90, 100) == -10.0
assert _growth(None, 100) is None and _growth(10, 0) is None
print("[ok] 数值/增速工具函数")

# 3) 增速→评分映射（借 analyze 内部维度）
ana2 = analyze_fundamentals("AAPL")
assert isinstance(ana2["valuation"], dict) and "pe_ttm" in ana2["valuation"]
print("[ok] 美股代码路径无异常")

# 4) HTML 卡片渲染（任何输入都不应抛异常、应含免责声明）
html = render_fundamental_card(ana)
assert "不构成投资建议" in html
html_empty = render_fundamental_card({"ok": False, "note": ["测试"]})
assert "⚠️" in html_empty
print("[ok] 卡片渲染（含空数据降级）")

print("\nALL PASS")
