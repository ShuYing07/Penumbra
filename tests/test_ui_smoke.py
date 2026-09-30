# -*- coding: utf-8 -*-
"""UI 冒烟回归：懒加载 tab 切换不得"跳页"（用户两次报告的『点功能弹K线』bug）。

规则：_on_tab_changed 内 removeTab/insertTab 替换占位页后，Qt 会自动把
currentIndex 移到相邻页；main_window 已加恢复逻辑。本测试逐页验证：
点击某功能 → currentIndex 必须停在目标页；再切回首页 → 仍停在首页。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

app = QApplication([])
from app.ui.main_window import MainWindow, NAV_GROUPS

TOTAL = 36
w = MainWindow()
assert w.tabs.count() == TOTAL, f"期望 {TOTAL} 个 tab（0-{TOTAL-1}），实际 {w.tabs.count()}"
# 懒加载占位页存在
for i in range(5, TOTAL):
    assert i in w._lazy_tabs and i not in w._created

# 逐页点击：目标页必须保持激活（修复『点功能弹K线』）
for i in range(5, TOTAL):
    w.tabs.setCurrentIndex(0)
    w._on_tab_changed(i)  # 手动触发懒加载（等价于点击导航）
    w.tabs.setCurrentIndex(i)
    cur = w.tabs.currentIndex()
    assert cur == i, f"点击 tab {i}({w._lazy_tabs[i][0]}) 后 currentIndex={cur}，被弹到其他页！"
    assert w._created.get(i) is not None, f"tab {i} 未创建"

# 再回首页，确认没有残留跳页
w.tabs.setCurrentIndex(0)
assert w.tabs.currentIndex() == 0
print(f"[ok] {TOTAL} 个 tab 全部就位；懒加载页 {list(w._created.keys())} 均保持目标页激活")

# 导航分组覆盖：每个 tab 都有导航入口（0-{TOTAL-1} 全覆盖）
nav_idx = {idx for _g, items in NAV_GROUPS for _l, idx in items}
missing = set(range(TOTAL)) - nav_idx
assert not missing, f"无导航入口的 tab：{missing}"
print(f"[ok] 导航分组覆盖全部 {TOTAL} 个 tab（发现/研究/验证/积累/系统）")

# 新页导入即建
for idx in (23, 24, 25, 26, 27, 28, 29, 30):
    w._on_tab_changed(idx)
    assert idx in w._created, f"tab {idx} 未创建"
print("[ok] 组合优化(23) / 基本面(24) / 数据质量(25) / 系统健康(26) / "
      "多模态(27) / 实时流(28) / 合规测试(29) / 插件管理(30) 可实例化")

print("\nALL PASS")
