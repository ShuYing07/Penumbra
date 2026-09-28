# 疏影·知微 企业版（ENTERPRISE）

**版本**：企业版路线图 v0.7.0+ · **定位**：在社区版（开源、本地、免费）之上，面向团队与机构提供隔离、协作、审计与部署能力。

---

## 一、为什么需要企业版

社区版是单用户本地桌面工具。企业客户需要：**数据隔离、权限控制、团队协作、审计追溯、可私有化部署**。企业版在保留"本地优先"核心的同时，补齐上述能力。

## 二、功能矩阵

| 能力 | 社区版（开源） | 企业版 |
|------|---------------|--------|
| 行情/指标/K线/回测 | ✅ | ✅ |
| 多模型 AI 分析 | ✅ | ✅ |
| 多租户数据隔离 | ❌ | ✅（独立数据文件/库 per 租户） |
| RBAC 权限（admin/analyst/viewer） | ❌ | ✅ |
| SSO（SAML/OIDC，预留） | ❌ | ✅（对接 Okta/Azure AD） |
| 操作审计日志（不可篡改+CSV导出） | ❌ | ✅ |
| 协作空间/评论/版本控制 | ❌ | ✅ |
| 外部数据源（Wind/Polygon/自定义） | 仅内置 | ✅ 订阅管理 |
| 组合风控（VaR/压力测试/归因） | ❌ | ✅ |
| 合规规则引擎（禁投/仓位上限） | ❌ | ✅ |
| REST API | ❌ | ✅（FastAPI） |
| 私有化部署（Docker/K8s） | ❌ | ✅ |

## 三、部署方式

### 方式 A：SaaS 云托管（规划中）
订阅制，多租户，自动升级。定价占位：
- 个人版 ¥99/月（云端 AI 额度）
- 团队版 ¥999/月（5 用户）
- 企业版 定制报价

### 方式 B：私有化部署（本仓库已含编排文件）
```bash
# Docker Compose（API + PostgreSQL + Redis + Worker）
cp .env.docker .env
docker compose up -d

# Kubernetes（Helm）
helm install shuying ./deploy/chart --values ./deploy/chart/values.yaml
```

### 方式 C：混合模式（核心数据本地，计算云端）
桌面版保留全部本地能力；企业 API 提供共享研究空间与审计，核心行情仍走本地缓存。

## 四、实施路线图

| 阶段 | 时间 | 核心任务 | 状态 |
|------|------|---------|------|
| 阶段一 | 1-3 个月 | GDPR/CCPA 合规、多租户隔离、RBAC、审计日志 | ✅ 代码已落地（本仓库） |
| 阶段二 | 3-6 个月 | 协作工作流、数据集成、组合风控、合规引擎 | ✅ 代码已落地（本仓库） |
| 阶段三 | 6-12 个月 | 企业版发布、插件系统、云市场上架 | 🚧 规划中 |
| 阶段四 | 12-18 个月 | 多语言、多市场、SOC 2 认证 | 🚧 规划中 |

## 五、已知边界与升级路径

1. **多租户存储**：当前为"独立 SQLite 文件 per 租户"，满足私有化部署起点；海量并发需迁移 PostgreSQL（`sqlalchemy` + 每租户 schema，接口已在 `core/tenant_manager.py` 预留 `tenant_conn()` 中间件）；
2. **SSO**：`core/auth_service.py` 提供本地 JWT + RBAC；SAML/OIDC 对接需部署 Keycloak/Auth0（编排文件已预留）；
3. **异步任务**：回测/AI 长任务建议接入 Celery + Redis（docker-compose 已含 worker 服务占位）；
4. **REST API**：`api/main.py` 已实现（需安装 fastapi + uvicorn 后启动，见 docs/API.md 或 README）；
5. **合规**：GDPR/CCPA 详见 docs/COMPLIANCE.md。

> 企业版功能与代码均为**研究学习用途**，不构成投资建议；金融合规以当地法规为准。
