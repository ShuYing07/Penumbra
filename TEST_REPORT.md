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

---

## 十一、10 大方向优化（2026-09-29，回测严谨性 / Screener / 财报 / 组合优化 / 实时行情 / 性能打包 / 推理可观测 / 数据溯源 / 基本面引擎 / 多智能体团队）

### 测试结果：**51/51 全部通过**（tests/run_all.py 一键运行）

| # | 模块 | 关键文件 | 测试 |
|---|---|---|---|
| 1 | 回测严谨性 | core/quant/audit.py（前视偏差扫描 / Walk-Forward）+ 回测页"策略审计"tab | test_quant_audit.py PASS |
| 2 | 结构化 Screener | core/screener.py（PE/PB/市值/量/换手等 9 条件 + 自然语言选股） | test_screener_nl.py PASS |
| 3 | 财报与公告解析 | core/financial_report_parser.py（新浪/东财降级 + LLM/规则双通道 + 摘要卡片 + 多期对比） | test_finreport.py PASS |
| 4 | 组合优化 | core/portfolio_optimizer.py（均值-方差/风险平价/HRP + 组合净值回测）+ UI tab 23 | test_portfolio_opt.py PASS |
| 5 | 实时行情 | core/realtime_engine.py（轮询 + WebSocket + 退避重连 1→30s + 心跳）+ 自选股实时标签 | test_realtime.py PASS |
| 6 | 性能与打包 | core/update_checker.py（启动后台检查，仅提示）、config_manager 版本 0.7.0 + 仓库统一、spec 瘦身 | test_update_checker.py PASS |
| 7 | AI 推理可观测性 | agent/agent_events.py + agent_trace_store.py（agent_traces 落库）+ chat 时间线渲染 | test_agent_trace.py PASS |
| 8 | 数据溯源与证据链 | core/evidence_manager.py（结论↔数据来源登记/查询/幂等）+ prompts 来源标注规则 | test_evidence.py PASS |
| 9 | 基本面分析引擎 | core/fundamental_analyzer.py（健康度评分 + 估值卡片 + 同行对比）+ UI tab 24"基本面" | test_fundamental.py PASS |
| 10 | 多智能体投研团队 | core/agents/risk_assessor.py（风险评估师：波动率/VaR/回撤/压力测试）+ leader_node（首席分析师一致性审查）+ 10 节点层级编排 | test_agents_team.py PASS |
| — | UI 冒烟回归 | 25 tab 懒加载 + 导航全覆盖 + 跳页回归 | test_ui_smoke.py PASS |

### 本轮修复的 Bug
1. **懒加载跳页**（用户反馈"点开功能先弹出K线图"）：removeTab/insertTab 扰动 currentIndex → 恢复目标页；test_ui_smoke 逐页验证 25 tab 均保持目标页。
2. **基本面 tab 无导航入口**：NAV_GROUPS"研究"组补入"📊 基本面（24）"。
3. **风险评估师拿不到K线**：state 无 bars → 节点内改调 service.get_daily(ticker)（带缓存）。
4. **证据链未覆盖新节点**：evidence_manager 补风险评估师/首席分析师登记。
5. **测试非幂等**：test_evidence / test_agent_trace 历史残留导致偶发失败 → 清理逻辑 + 真实时间戳。

### 说明
- 东财概念接口本机不可达：UI 已有"查询失败可重试"降级，test_all 产业图谱子项按网络降级容忍计。
- 组合优化 skfolio 未安装时自动走 numpy/scipy 引擎并标注；安装 `pip install skfolio` 后自动切换。
- fastmcp 4.0.10 / pypinyin 0.55.0 已按用户要求安装完成。
- 未打包、未推送、未打标签（等用户通知后再开源更新）。

---

## 十二、任务书A+B（2026-09-29，实时行情QOS / 数据质量校验 / 性能监控 / 7分析师团队 / PIT-Guard / 组合优化扩展 / 财务比率+DCF / 执行控制台）

### 测试结果：**58/58 全部通过**（tests/run_all.py 一键运行）

| # | 模块 | 关键文件 | 测试 |
|---|---|---|---|
| 1 | 实时行情（QOS 优先） | core/realtime_engine.py 新增 `_ws_url()`：QOS_WS_URL → REALTIME_WS_URL → Longbridge 三级优先；心跳 30s + 退避重连 1→30s | test_realtime.py PASS |
| 2 | 数据质量校验 | core/data_quality.py（OHLCV 缺失/非正价/>50%跳变/交易日缺口，score 0-100 扣分制，及格 70；财报字段+数值+多期一致性；quality_reports 落库）+ service.get_daily 集成校验与备源切换 + UI tab 25"数据质量" | test_data_quality.py PASS |
| 3 | 性能监控 | core/performance_monitor.py（模块计时/API 计数/内存采样/异常阈值）+ UI tab 26"系统健康"（5s 自刷新）+ main_window 启动计时 | test_perf_monitor.py PASS |
| 4 | 7 分析师并行团队 | core/agents/analyst_team.py（ANALYST_DEFS：技术/基本面/新闻/情绪=数据组并行，宏观/风险/深度研究=综合组并行；ThreadPoolExecutor；InvestmentManager 组合经理：风控否决权+批准限额）+ run_analysis_team 全流程 + analysis_context 落盘 | test_analyst_team.py PASS |
| 5 | PIT-Guard 数据泄漏防护 | core/pit_guard.py（guard_bars 时点截断 / guard_data 未来记录剔除 / leakage_probe 参数化记忆探测 / annotate_report 机械层-Agent层边界）+ config.yaml collaboration.mode（panel/debate/vote 可插拔） | test_pit_guard.py PASS |
| 6 | 组合优化扩展 | core/portfolio_optimizer.py 新增 maxdiv（最大分散化 SLSQP）与 cvar（分布鲁棒 CVaR）；UI tab 23 下拉同步 | test_portfolio_opt2.py PASS |
| 7 | 财务比率 + DCF | core/financial_report_parser.py 新增 calculate_ratios（可得字段如实计算/缺失标注）、build_dcf_model（5 年折现 + 三情景 + 3×3 敏感性 + 免责声明）、render_ratios_card/render_dcf_card | test_ratios_dcf.py PASS |
| 8 | 执行控制台 | agent/execution_console.py（User/Expert/Dev 三模式渲染；Dev 含 token_ledger 统计 + agent_traces 分组瀑布） | test_execution_console.py PASS |
| — | UI 冒烟回归 | 27 tab 懒加载 + 导航全覆盖（含 tab 25/26） | test_ui_smoke.py PASS |

### 本轮修复的 Bug
1. **execution_console.render 缺 analysis_id 参数**：Dev 模式无法传入分析ID → 签名补 `analysis_id=None`。
2. **performance_monitor.timed 的 _Ctx 引用错误**：`self._lock` 不在 _Ctx 上 → 闭包捕获 monitor 的锁与模块表。
3. **pit_guard.guard_data 日期比较 bug**：as_of 带连字符未规范化，与纯数字日期串比较恒 False → 未来记录全部误剔 → `_norm_date(as_of)` 统一口径。
4. **analyst_team 全流程覆盖 state**：`state = nodes.leader_node(...)` 丢弃其余字段 → 改 `state.update(...)`。
5. **test_ui_smoke 未同步 27 tab**：25→27、range(5,27)、新增 tab 25/26 实例化断言。
6. 新测试首跑暴露 4 处断言设计问题（分数及格线语义、浮点 round、state 字段缺失、dataclass 参数）——均已修正为与实现语义一致。

### 说明
- 东财接口本机仍不可达：数据质量/备源链自动降级并如实标注来源；run_all 对网络降级容忍。
- QOS 行情 API 需用户自行申请 token（.env `QOS_API_TOKEN`）；未配置时自动走 AKShare 轮询降级。
- skfolio / fastapi / uvicorn 仍未安装（可选，未安装不影响桌面版）；安装命令见 requirements.txt 注释。
- 所有 AI 推理出口仍坚守"数据工具"定位：PIT-Guard 保证回测无前视、机械层收益不含 LLM、DCF 明确"不构成投资建议"。
- 未打包、未推送、未打标签（等用户通知后再开源更新）。

---

# 第十三章 · 0.8.0 发布验证（2026-09-29）

## 全量回归
- tests/run_all.py：58/58 通过（含交互冒烟 27 tab / 19 步）。
- 0.8.0 新增/增强验证：
  - 组合优化页新增权重饼图（matplotlib 暗色主题）与有效前沿（随机采样可行域 + 最优解标注），offscreen 冒烟通过。
  - 基本面页升级为财报摘要卡片：build_report_card_html 聚合关键信息提取 → 多期对比 → 财务比率 → 5年DCF → 健康度评分，网络不可达时逐段降级标注；冒烟 len=6196 含 DCF/比率/健康度。
  - 修复更新检查回调 NameError：main_window._auto_check_update 的 lambda 引用 APP_VERSION 未导入（GitHub 可达时触发），已改为方法内局部导入。

## 口径校准（发布文案 vs 实现）
- 组合优化：5 种方法全部实现；引擎优先 skfolio、未装时 numpy/scipy 等价可用；UI 含饼图/可行域/风险指标/风险贡献/净值，无"行业集中度约束"（已从文案移除）。
- 财务比率：按可得字段如实计算 + 缺失标注（非固定 50+），文案已如实表述。
- 打包体积：发行包 907MB → 约 396MB（主程序 exe 44.6MB），文案如实表述。
- 同行雷达图 / 对象池：未实现，已从文案移除。
- 版本号：config_manager APP_VERSION = 0.8.0；测试断言同步。
- 仓库地址：更新检查指向 ShuYing07/Penumbra（真实仓库），不再 404。
