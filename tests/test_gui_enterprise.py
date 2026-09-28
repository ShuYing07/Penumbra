# -*- coding: utf-8 -*-
"""GUI 冒烟（企业版UI集成）：构建 MainWindow，切换全部 tab（含企业版 17-20），验证核心交互。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("STOCKAI_MOCK", "1")
sys.path.insert(0, r"D:\StockAIPredictor")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

app = QApplication([])

_timed_out = {"v": False}


def _timeout():
    _timed_out["v"] = True
    print("FAIL 全局超时（异步网络线程可能挂起）")
    app.exit(2)


QTimer.singleShot(60_000, _timeout)

from app.ui.main_window import MainWindow

win = MainWindow()
win.show()
app.processEvents()

tabs = win.tabs
n = tabs.count()
print(f"PASS 窗口构建，tab 总数 = {n}")
assert n >= 21, f"tab 数不足: {n}"

# 逐个切换懒加载 tab（5..20），确认创建成功
for idx in range(5, n):
    tabs.setCurrentIndex(idx)
    app.processEvents()
    w = tabs.widget(idx)
    assert w is not None, f"tab {idx} 创建失败"
    print(f"PASS tab[{idx}] {tabs.tabText(idx)} -> {type(w).__name__}")

# 企业版 tab 功能冒烟
# 17 协作空间
tabs.setCurrentIndex(17)
app.processEvents()
collab = tabs.widget(17)
import uuid
collab.name_edit.setText(f"GUI冒烟{uuid.uuid4().hex[:4]}")
collab._create_ws()
app.processEvents()
assert collab.ws_list.count() >= 1, "协作空间创建失败"
print("PASS 协作空间：创建+列表")

# 18 风控（不联网：持仓解析+合规检查本地路径）
tabs.setCurrentIndex(18)
app.processEvents()
risk = tabs.widget(18)
risk.positions.setPlainText("600519,0.5,消费\nAAPL,0.5,科技")
risk._compliance()
app.processEvents()
assert risk.table.rowCount() >= 1
print(f"PASS 风控：合规检查 {risk.table.rowCount()} 行")
# 合规检查是本地逻辑；VaR需要联网行情，在此跳过（单元测试已覆盖）

# 19 数据源
tabs.setCurrentIndex(19)
app.processEvents()
ds = tabs.widget(19)
assert ds.catalog.rowCount() >= 5, "数据源目录未加载"
print(f"PASS 数据源：目录 {ds.catalog.rowCount()} 条")
from core.data_marketplace import subscribe
subscribe("local", "tushare")
ds.refresh()
assert "tushare" in ds.status_label.text()
print("PASS 数据源：订阅状态刷新")

# 20 隐私
tabs.setCurrentIndex(20)
app.processEvents()
privacy = tabs.widget(20)
privacy.refresh()
assert "v" in privacy.policy_label.text()
print("PASS 隐私：政策版本展示")
privacy._delete_dry()
assert "预演" in privacy.log.toPlainText()
print("PASS 隐私：删除预演")

print("\n==== GUI 冒烟全部通过 ====")
win.close()
app.exit(0)
