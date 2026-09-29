# -*- coding: utf-8 -*-
"""模块六：性能/更新检查测试。"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

# 1) 仓库常量一致性（真实仓库 ShuYing07/Penumbra，勿指向不存在的 StockAIPredictor）
from config_manager import APP_VERSION, REPO_API, REPO_URL, RELEASES_URL
assert "StockAIPredictor" not in REPO_API and "StockAIPredictor" not in REPO_URL, (REPO_API, REPO_URL)
assert "Penumbra" in REPO_API and "Penumbra" in REPO_URL and "Penumbra" in RELEASES_URL
assert APP_VERSION == "0.8.0", APP_VERSION
print("[ok] 仓库/版本常量:", APP_VERSION, REPO_URL)

# 2) 异步更新检查：不阻塞主线程 + 回调触发（网络不可达时静默返回）
from core.update_checker import check_updates_async
results = []


def _res(res):
    results.append(res)


t0 = time.time()
check_updates_async(on_result=_res)
# 调用后立即返回（异步）
assert time.time() - t0 < 1.0, "异步检查不应阻塞调用方"
deadline = time.time() + 12
while not results and time.time() < deadline:
    time.sleep(0.3)
assert results, "12s 内未收到更新检查回调"
res = results[0]
assert isinstance(res, dict) and "has_update" in res and "current" in res
print(f"[ok] 更新检查回调：has_update={res['has_update']} latest={res['latest']} error={res['error']}")

# 3) 检查函数本身幂等、字段完整
from config_manager import check_update
r2 = check_update(timeout=3.0)
assert set(["current", "latest", "has_update", "url", "error"]) <= set(r2.keys())
print("[ok] check_update 字段完整")

print("\nALL PASS")
