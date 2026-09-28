# REST API 文档（模块三）

企业版 REST 服务。**启动前需手动安装**：
```bash
pip install fastapi uvicorn[standard]
```

## 启动
```bash
venv\Scripts\python.exe -m api.main          # http://127.0.0.1:8000
# 交互式文档（Swagger UI）
# http://127.0.0.1:8000/docs
```

## 端点一览

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET  | /health | 无 | 健康检查 |
| POST | /auth/login | 无 | 登录，返回 JWT |
| GET  | /analysis/{stock_code} | analyst | 获取行情分析摘要（纯数据统计） |
| POST | /backtest | analyst | 提交回测任务 |
| GET  | /portfolio | viewer | 组合信息 |
| GET  | /audit-log | admin | 审计日志（CSV 可导出） |

## 认证
登录获取 `access_token`，后续请求带：
```
Authorization: Bearer <token>
```
令牌 8 小时有效；角色：`admin` / `analyst` / `viewer`（RBAC 见 core/auth_service.py）。

## 示例
```bash
# 登录
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"Passw0rd!"}'

# 分析
curl http://127.0.0.1:8000/analysis/SH600519 \
  -H "Authorization: Bearer <token>"
```

> API 仅供数据统计与研究学习，不构成任何投资建议。
