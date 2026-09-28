# -*- coding: utf-8 -*-
"""企业版 REST API 语法与依赖检查。

- fastapi 已安装 → 导入 app 并做冒烟（构造请求）；
- fastapi 未安装 → 报告需手动安装，仍校验 api/models.py、dependencies.py 可导入。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = True
try:
    import fastapi  # noqa: F401
    have_fastapi = True
except Exception:  # noqa: BLE001
    have_fastapi = False

# 1) 纯 Python 模块必须能导入（不依赖 fastapi）
from api.dependencies import get_current_user  # noqa: F401,E402
from core.auth_service import create_token  # noqa: F401,E402
print("PASS api/dependencies + core/auth_service 可导入")

# 2) 语法编译检查（即使无 fastapi 也验证所有 api 文件语法）
import py_compile

for f in ("api/main.py", "api/models.py", "api/dependencies.py"):
    py_compile.compile(f, doraise=True)
print("PASS api/*.py 语法编译通过")

if not have_fastapi:
    print("SKIP fastapi 未安装 —— 请手动安装：pip install fastapi uvicorn[standard]")
    print("      （未安装不影响桌面版；安装后运行 python -m api.main 即可启动 API）")
    sys.exit(0)

# 3) fastapi 存在 → 真实冒烟
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)
r = client.get("/health")
assert r.status_code == 200 and r.json()["status"] == "ok"
print("PASS /health")

# 登录（先在 auth.db 建测试用户；用户名带时间戳，重复运行不冲突）
from core import auth_service, tenant_manager
import time as _time

t = tenant_manager.tenant_register("API测试企业")
user = f"api_user_{int(_time.time())}"
auth_service.register_user(t["tenant_id"], user, "Test1234!", role="admin")
r = client.post("/auth/login", json={"username": user, "password": "Test1234!"})
assert r.status_code == 200, r.text
tok = r.json()["access_token"]
print("PASS /auth/login")

r = client.get("/analysis/SH600519", headers={"Authorization": f"Bearer {tok}"})
assert r.status_code == 200, r.text
print("PASS /analysis/SH600519 ->", r.json()["summary"])

r = client.get("/audit-log", headers={"Authorization": f"Bearer {tok}"})
assert r.status_code == 200 and isinstance(r.json(), list)
print(f"PASS /audit-log（{len(r.json())} 条）")

r = client.get("/analysis/AAPL")  # 无 token
assert r.status_code == 401
print("PASS 无token被拒绝(401)")

print("\n==== API 冒烟全部通过 ====")
