# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STOCKAI_MOCK", "1")

# drawings 元数据更新
from core.drawings import save_drawing, list_drawings, update_drawing_meta, delete_drawing
did = save_drawing("TEST", "hlevel", [{"x": 1, "y": 100.0}], {"color": "#00E5FF"})
assert did > 0
assert update_drawing_meta(did, {"color": "#FFA726"})
ds = list_drawings("TEST")
assert ds and ds[-1]["meta"]["color"] == "#FFA726", ds
delete_drawing(did)
print("[ok] update_drawing_meta")

# chart_tab 新增方法存在
from app.ui.chart_tab import ChartTab
for m in ("_toggle_fav", "_load_favs", "_toggle_eraser", "_erase_last",
          "_on_plot_right_click", "_recolor_last"):
    assert hasattr(ChartTab, m), m
print("[ok] ChartTab 绘图深化方法:", "磁吸/收藏/橡皮擦/右键样式")

print("\nALL PASS")
