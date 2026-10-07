# -*- coding: utf-8 -*-
"""第17轮·模块五：知识图谱增强测试（FinKG-News 事件锚定 + HERMES 动态演化）。

不改动既有 eg_nodes/eg_edges schema，新增锚定表 + 时序实体表；验证：
- 时序实体识别（公司/人物/宏观/行业）
- 事件锚定（日期/实体/情感/来源）
- 新闻流批量锚定
- HERMES 动态演化（时间衰减：alive / stale 实体）
- 锚定事件查询（日期下限 / 情感阈值过滤）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

from core import event_graph as eg

ENTITY = "600519"

# 1) 时序实体识别（HERMES 风格规则 NER）
txt1 = "贵州茅台董事长表示，央行降准利好白酒与半导体行业"
ents = eg.recognize_entities(txt1)
kinds = {e["kind"] for e in ents}
names = {e["name"] for e in ents}
assert "company" in kinds and "贵州茅台" in names, ents
assert "person" in kinds and "董事长" in names
assert "macro" in kinds and "央行" in names
assert "industry" in kinds and "白酒" in names and "半导体" in names
print(f"[ok] 时序实体识别：{ents}")

# 2) 事件锚定（FinKG-News 风格）
a = eg.anchor_event(ENTITY, "贵州茅台业绩预增，净利润同比增长15%", date="2024-03-10", source="财联社")
assert a["etype"] == "业绩预增", a
assert a["date"] == "20240310", a
assert a["sentiment"] > 0, a   # 预增/增长 → 正面
assert any(e["name"] == "贵州茅台" for e in a["entities"])
print(f"[ok] 事件锚定：etype={a['etype']} date={a['date']} sentiment={a['sentiment']} ents={[e['name'] for e in a['entities']]}")

# 负面事件情感应 < 0
a2 = eg.anchor_event(ENTITY, "某股东减持套现，业绩预减暴雷", date="2024-05-20")
assert a2["sentiment"] < 0, a2
print(f"[ok] 负面事件情感={a2['sentiment']}（<0）")

# 3) 新闻流批量锚定
stream = [
    {"text": "央行宣布降准，释放流动性", "date": "2024-03-01", "source": "央行"},
    {"text": "贵州茅台签约重大合同", "date": "2024-04-15", "source": "公告"},
    {"text": "半导体行业景气度回暖", "date": "2024-06-01", "source": "研报"},
]
res = eg.build_from_news_stream(ENTITY, stream)
assert res["anchored"] == 3, res
print(f"[ok] 新闻流批量锚定：{res['anchored']} 条，识别实体 {res['entities']}")

# 4) 锚定事件查询（日期下限 + 情感过滤）
all_a = eg.query_anchored(ENTITY)
assert len(all_a) >= 5, all_a
recent = eg.query_anchored(ENTITY, since="2024-04-01")
assert all(r["date"] >= "20240401" for r in recent), recent
neg = eg.query_anchored(ENTITY, sentiment_le=0.0)
assert all(r["sentiment"] <= 0 for r in neg), neg
print(f"[ok] 锚定查询：总 {len(all_a)} 条；≥2024-04-01 的 {len(recent)} 条；负面 {len(neg)} 条")

# 5) HERMES 动态演化：时间衰减（alive / stale）
# 用较近 as_of → 近期实体 alive；远于 2×half_life → stale
ev = eg.evolve(ENTITY, as_of="2024-06-10", half_life_days=30)
assert "alive_entities" in ev and "stale_entities" in ev
# 2024-03-01 的"央行"距 06-10 约 100 天 > 2×30 → stale
assert "央行" in ev["stale_entities"], ev
# 2024-06-01 的"半导体"距 06-10 < 30 → alive
assert "半导体" in ev["alive_entities"], ev
print(f"[ok] HERMES 演化：alive={ev['alive_entities']} stale={ev['stale_entities']}")

# 6) 既有接口未被破坏（回归）
from memory.event_extractor import extract_event_type
b = eg.build_from_texts(ENTITY, ["贵州茅台业绩预增", "股东减持"], industry="白酒")
assert b["events"], b
chain = eg.query_event_chain(ENTITY, depth=3)
assert chain["nodes"] and chain["path"]
imp = eg.predict_impact(ENTITY, ["贵州茅台业绩预增"], "白酒")
assert imp["risk_scores"]
print(f"[ok] 既有接口回归通过（nodes={b['nodes']}，风险={imp['summary']}）")

print("\nALL PASS")
