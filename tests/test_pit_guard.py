# -*- coding: utf-8 -*-
"""任务书B·模块二：PIT-Guard 数据泄漏防护测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import pandas as pd
from core.pit_guard import (guard_bars, guard_data, leakage_probe,
                            annotate_report, load_collaboration_config)

# 1) guard_bars：截断到 as_of
idx = pd.date_range("2026-01-01", periods=60, freq="B")
df = pd.DataFrame({"close": range(60)}, index=idx)
cut = guard_bars(df, "2026-02-15")
assert cut.index.max().strftime("%Y-%m-%d") <= "2026-02-15"
assert len(cut) < len(df)
# 空 as_of 原样返回
assert len(guard_bars(df, "")) == len(df)
print("[ok] guard_bars 截断")

# 2) guard_data：剔除未来记录
payload = {"rows": [{"date": "2026-01-10", "v": 1}, {"date": "2026-12-31", "v": 2}]}
gd = guard_data("news", payload, "2026-06-30")
assert gd["filtered"] >= 1, gd
assert len(gd["data"]["rows"]) == 1, gd
assert gd["data"]["rows"][0]["date"] == "2026-01-10"
# 无 as_of → 放行不过滤
gd2 = guard_data("news", payload, "")
assert gd2["allowed"] and gd2["filtered"] == 0
print("[ok] guard_data 未来记录剔除")

# 3) leakage_probe：干净回答 vs 泄漏回答
clean = leakage_probe(lambda q: "无法预知未来事件，建议关注官方披露。")
assert clean["verdict"] == "clean"
leak = leakage_probe(lambda q: "2026年12月31日后，A股发生重大政策调整，具体为X。",
                     keywords=["政策调整"])
assert leak["verdict"] == "leak"
print("[ok] leakage_probe 探测:", clean["verdict"], leak["verdict"])

# 4) annotate_report：机械层/Agent层标注
rep = annotate_report({"ret": 1.2})
assert "mech_layer" in rep and "agent_layer" in rep and "pit_guard" in rep
print("[ok] 机械层/Agent层边界标注")

# 5) collaboration 配置：默认 debate + 文件覆盖
cfg = load_collaboration_config()
assert cfg["mode"] in ("panel", "debate", "vote")
assert "rounds" in cfg["debate"]
print("[ok] collaboration 配置:", cfg["mode"])

print("\nALL PASS")
