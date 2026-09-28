# 测试报告（TEST_REPORT）

**项目**：疏影·知微（Shuying Insight / Penumbra）
**日期**：2026-09-28
**执行环境**：Windows · Python 3.14 (venv) · QT_QPA_PLATFORM=offscreen

---

## 一、测试结果总览

| 测试组 | 文件数 | 通过 | 失败 |
|--------|--------|------|------|
| 端到端冒烟（tests/test_all.py） | 1 | 10/10 | 0 |
| 量化模块单元测试（tests/test_*.py） | 25 | 25/25 | 0 |
| **合计** | **26** | **35/35** | **0** |

### 端到端冒烟 10 项（test_all.py）
数据-日线 / 数据-实时价（休市兜底） / 技术指标 / 合规过滤（买入→【已过滤】） / 多空辩论模块 / 回测引擎 / 产业图谱 / 本地AI检测 / 配置API Key / .env.example 完整性。

---

## 二、本轮（2026-09-28）修复与优化清单

### 模块一：沪深300历史数据
- 核验 `core/data/service.py`：已有 12 个指数映射（000300→东财/新浪/Tushare/yfinance），三级降级链实测 `get_daily("000300")` 返回 **6000+ 行**（东财源失败自动降级新浪源，最新收盘 4439.14 / 2026-09-24）。
- 优化：缓存新鲜度由"最近交易日"改为 **7 个自然日容忍**，长假/休市不再反复联网。

### 模块二：错误处理降级
- 核验 `core/error_handler.py` 完整：`handle_network_error` / `show_non_blocking_error`（5秒淡出横幅）/ `check_network_and_fallback`（网络→缓存→示例贵州茅台）/ `network_status_bar`（状态栏红字+重试按钮）。
- 市场概览失败路径已接入非阻塞提示，启动不再被网络弹窗阻塞。

### 模块三：README 与 FAQ
- `docs/FAQ.md`：0.7KB → **4KB**（API Key 配置、沪深300数据源、本地模型、常见报错、隐私、合规）。
- `README.md`：新增"🧠 本地模型（可选，完全离线）"章节。

### 模块四：模型目录说明
- 新建 `models/README.md`：放置路径、下载源（HF/ModelScope/Ollama）、不下载自动降级说明。
- `.gitignore`：增加 `!models/README.md` + 临时输出清单（out/err/stdout/stderr.txt、各 *.log）。

### 模块五：测试与项目结构
- 根目录 **15 个 test_\*.py** 移入 `tests/`（UTF-8 读改写，无编码损坏）；创建 `tests/__init__.py`。
- 修正 `test_all.py` 及 3 个受路径影响测试的 `sys.path`（test_aapl / test_broker_links / test_search），修复后 3/3 复测通过。
- 清理根目录 **11 个临时文件**（local_run\*.log、ollama_pull\*.log、pack_build\*.log、out/err/stdout/stderr.txt）。

### 模块六~八：核验（已实现，不重做）
- **持久化记忆**：`core/memory/long_term.py`（analysis_history / knowledge_facts / user_prefs 表 + save_analysis）；`core/memory/rag.py`（ChromaDB 持久化 + 离线哈希嵌入 + `retrieve_similar` 语义检索）；`app/ui/history_tab.py` 历史分析页。
- **多模型路由**：`core/model_router.py` 支持 deepseek / glm / groq 等 OpenAI 兼容平台自动降级。
- **首次启动**：`app/main.py` 新手引导（3 页可跳过）+ 默认加载 AAPL + 免责声明/API 引导均记住选择。

### 模块九：社交预览与推广素材
- `docs/social-preview.png`（1280×640）与三张界面截图（main/chart/debate）已存在并被 README 引用。
- 新建 `docs/DEMO_GUIDE.md`（30 秒 Demo 录制指引）。
- 新建 `.github/TOPICS.md`（14 个推荐 Topics 标签）。

---

## 三、数据准确性验证

| 标的 | 接口 | 结果 |
|------|------|------|
| 沪深300（000300） | AKShare 东财→新浪降级 | 6000+ 行日线，最新收盘 4439.14 |
| 贵州茅台（SH600519） | AKShare 新浪 | 6012 行缓存 |
| 市场概览 6 指数 | 新浪实时 hq.sinajs.cn | 上证/深证/创业板/沪深300/中证500/上证50 全部返回 |

---

## 四、历史修复（前几轮累计，回归验证通过）

1. `no such table: daily_bars` —— 连接时自动幂等建表。
2. 休市实时价 0 / -100% —— 自动用最新日线收盘兜底。
3. 图标未打进 exe —— spec 加入 assets，兼容 `sys._MEIPASS`。
4. 首次启动 NameError —— welcome 函数定义顺序修复。
5. 模拟盘 `no such table: decisions` —— 首次运行自动建表（decisions/trades/positions）。
6. 搜索"腾讯"排序 —— 多准则加权排序（代码>名称>拼音，A股>港股>美股）。
7. K线 Y 轴 0.1~0.9 —— 数据加载后动态 setYRange，空数据显式提示。
8. 窗口跑出屏幕外 —— saveGeometry/restoreGeometry + 屏幕边界校验重置居中。
9. 免责声明每次弹窗 —— 非模态 + QSettings 记住选择。
10. 分析结果全 [MOCK] —— 引擎状态显示 + 自动降级本地模型/MOCK。

---

## 五、已知限制

1. 东财源在当前网络环境每次被 `RemoteDisconnected` 断开（数秒后自动降级新浪源）——7 天缓存规避后正常路径直接走缓存。
2. Release 附件（360MB ZIP）多次上传失败（`ConnectionResetError`），README 一键下载链接尚未挂上附件，需换通道上传（git-lfs / 分块 / 手动）。
3. 默认演示标的为 AAPL（美股），首次启动需联网；无网络自动降级缓存/示例。

---

## 六、运行方式

```bash
# 一键运行全部测试（离线优先，不真调 LLM）
venv\Scripts\python.exe tests\test_all.py

# 运行单个测试
venv\Scripts\python.exe tests\test_backtest.py
```

---

## 七、结论

自动化层面全部通过（35/35），本轮修复与文档优化全部落地且回归无破坏。GUI 交互项请按 `MANUAL_TEST_CHECKLIST.md` 人工确认；打包产物待用户手动测试后再打新版本标签。

---

## 八、企业版升级（2026-09-28，模块一~八）

### 测试结果：企业版 11/11 通过（tests/test_enterprise.py）

| 模块 | 交付文件 | 测试 |
|------|---------|------|
| 一 合规隐私 | core/privacy_compliance.py（GDPR导出/删除/同意）、core/audit_logger.py（操作审计+CSV）、PRIVACY.md/TERMS 追加 GDPR/CCPA | PASS |
| 二 多租户+认证 | core/tenant_manager.py（独立库per租户+隔离中间件）、core/auth_service.py（PBKDF2+JWT+RBAC，标准库实现） | PASS |
| 三 REST API | api/main.py、api/models.py、api/dependencies.py + docs/API.md | 语法通过（fastapi未装，安装后运行 python -m api.main） |
| 四 协作工作流 | core/collaboration.py（空间/评论/版本控制） | PASS |
| 五 数据集成 | core/data_connector.py（CSV/Excel导入+外部DB）、core/data_marketplace.py（数据源订阅） | PASS（修复日期index口径bug） |
| 六 风控合规 | core/risk_engine.py（VaR/压力测试/归因）、core/compliance_checker.py（禁投/仓位上限） | PASS |
| 七 部署运维 | docker-compose.yml、Dockerfile、.env.docker、deploy/chart/（Helm） | 文件就绪（需Docker环境） |
| 八 国际化文档 | core/i18n.py（中英切换）、docs/ENTERPRISE.md、docs/COMPLIANCE.md、README企业版章节 | PASS |

### 需手动安装的可选依赖（不影响桌面版）
```
pip install fastapi uvicorn[standard]      # REST API 服务
pip install python-jose[cryptography] passlib[bcrypt]   # 生产认证（可选）
pip install psycopg2-binary pymysql        # 外部数据库连接（可选）
pip install redis celery                   # 任务队列/缓存（可选）
```

### 关键设计说明
- 多租户：独立 SQLite 文件 per 租户（私有化部署起点），`tenant_conn()` 为唯一数据入口，禁用即隔离；
- 认证：JWT 用标准库 HMAC-SHA256 实现（无新依赖），升级 PostgreSQL/Keycloak 接口不变；
- 合规：GDPR 数据导出/删除可审计；操作审计追加式不可篡改+CSV导出；合规规则引擎自动检查投资限制；
- 部署：docker-compose 编排 API+PostgreSQL+Redis+Worker；Helm Chart 模板就绪。

---

## 九、企业版 UI 集成（2026-09-28 收尾）

### 交付：桌面端 4 个企业版标签页 + 可选登录

| 文件 | 说明 |
|------|------|
| app/ui/collaboration_tab.py | 协作空间：创建/选择空间、按资源评论、版本提交/回滚 |
| app/ui/risk_tab.py | 风控中心：组合 VaR / 压力测试 / 收益归因 / 合规规则检查 |
| app/ui/data_source_tab.py | 数据源管理：目录订阅/退订、CSV/Excel 导入行情缓存 |
| app/ui/privacy_tab.py | 隐私与数据：GDPR 导出 / 删除预演+执行 / 同意记录 / 审计CSV导出 |
| app/ui/login_dialog.py | 企业登录（默认关闭，QSettings enterprise_login 或 STOCKAI_LOGIN=1 开启） |

### 注册（app/ui/main_window.py）
- 懒加载 tab 扩展至 21 个：17 协作空间 / 18 风控 / 19 数据源 / 20 隐私与数据
- 左侧导航新增对应 4 项按钮

### 测试：GUI 冒烟全通过（tests/test_gui_enterprise.py，60s 超时保护）
- 21 个 tab 逐个懒加载创建成功
- 协作空间：创建 + 列表 PASS
- 风控：合规检查（禁投/仓位/行业上限）PASS
- 数据源：目录 5 源 + 订阅状态刷新 PASS
- 隐私：政策版本展示 + 删除预演 PASS

### 全量回归
- tests/test_all.py：10/10 通过
- tests/test_enterprise.py：11/11 通过（幂等唯一命名，可重复运行）
- tests/test_gui_enterprise.py：GUI 冒烟全通过

### 说明
- 风控 VaR/压力测试需联网行情，GUI 层仅验证本地合规检查；数值逻辑已由单元测试覆盖。
- 登录为可选开关，默认不影响普通用户。

---

## 十、企业深化八模块（2026-09-28，Agent Mesh / 零信任 / 双层级记忆 / 混合推理 / 数据网格 / 流处理 / Web混合 / 合规深化）

### 测试结果：12/12 通过（tests/test_enterprise_deep.py）

| 模块 | 交付 | 测试要点 |
|------|------|---------|
| 一 Agent Mesh | agent_mesh/{agent_registry,agent_identity,policy_engine,observability}.py | 注册/发现/注销、HMAC身份令牌+伪造拦截、PEP/PDP策略（deny-by-default）、通信日志+决策账本 |
| 二 零信任 | security/{zero_trust,audit_ledger}.py | 持续认证+上下文授权（时段/来源/风险分）、SHA-256哈希链审计+篡改检测+CSV/JSON导出 |
| 三 双层级记忆 | memory/{vector_memory,graph_memory,hybrid_memory}.py | 向量检索（chromadb可用则用，否则SQLite哈希向量降级）、图记忆BFS+影响链、向量+图+BM25融合 |
| 四 混合推理 | reasoning/hybrid_reasoner.py + config | 任务类型→策略选择（auto/structured/retrieval）、置信度门控（gate纯函数，边界值拦截） |
| 五 数据网格 | data_mesh/{domain_registry,data_catalog,data_contract}.py | 4域注册、目录按域检索、数据契约行级/批量校验+SLA |
| 六 实时流处理 | streaming/{event_bus,data_ingestion,stream_processor}.py | asyncio发布订阅、背压丢弃计数、窗口计算（5分钟均值）+异动触发 |
| 七 Web混合 | web_ui/{app.py,static/index.html} + main.py按钮 | FastAPI（/api/analysis、/api/bars、/api/backtest、/ws/analysis）+纯JS Canvas K线（无CDN）+桌面"打开Web界面"按钮（未装fastapi时友好提示） |
| 八 合规深化 | compliance/{gdpr,ccpa}.py + PRIVACY/TERMS | GDPR可携/删除封装、CCPA不出售声明与偏好持久化、文档追加 |

### 修复的 Bug（深化轮次）
1. security/audit_ledger.py append：SELECT 未含 seq 列却访问 → IndexError（改为 SELECT seq,hash）
2. 8 个新模块 _conn()：连接不关闭 → 文件锁/句柄泄漏（统一 contextmanager+closing）
3. 同上：closing 关闭连接时未提交事务被回滚 → 新增 yield 后 con.commit()
4. web_ui/app.py：fastapi 未装时 BaseModel NameError → 条件导入+future annotations

### 全量回归
- tests/test_all.py：10/10
- tests/test_enterprise.py：11/11（幂等）
- tests/test_enterprise_deep.py：12/12（幂等，独立临时库）
- tests/test_gui_enterprise.py：GUI 冒烟全通过（21 tab + Web 按钮注册）

### 说明
- 记忆/图谱全部零依赖可降级：chromadb/neo4j 未装时自动走 SQLite 实现（接口不变，后续可平滑升级）；
- Web UI 与 REST API 需 `pip install fastapi uvicorn[standard]` 后启用（桌面端未装时给出安装提示）；
- 所有 AI/推理输出仍坚守"数据工具"定位，门控拒绝数据不足的结论（合规红线）。
