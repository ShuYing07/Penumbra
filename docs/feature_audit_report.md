# 疏影·知微 v0.7.0 功能全面检测报告

- 检测时间：2026-09-29 12:04:33
- 检测耗时：66 秒
- 结果：**30 通过 / 0 失败 / 1 警告**（共 31 项）

| 模块 | 结果 | 说明 |
|---|---|---|
| 数据/沪深300指数 | PASS | 6001 行（源=network(+6001)） |
| 数据/A股日线(600519) | PASS | 6013 行 |
| 数据/美股(AAPL) | PASS | 500 行 |
| 数据/港股(0700.HK) | PASS | 492 行 |
| 数据/市场概览(指数) | PASS | 6 个指数, 示例 上证指数 3826.5(+0.08%) |
| 数据/股票索引 | PASS | 18331 条, 关键标的齐全 |
| 数据/命令面板索引 | PASS | 18331 条, tencent别名=True, 0700.HK=True |
| GUI/主窗口构建 | PASS | 23 tabs, 双Dock, 浮动AI按钮 |
| GUI/K线加载联动 | PASS | 6013根(worker_running=False status='SH600519 · 共 6013 根（显示 250）[cache] · 最新收盘 1243.88') |
| GUI/AI分析全链路(mock) | PASS | 完成· |
| GUI/决策记录落库 | PASS | 1 条 |
| GUI/回测引擎 | PASS | 6013根K线, 净值6013点, 收益6957.02%, 缺失指标:无 |
| GUI/参数寻优 | PASS | 4组合 best={'fast': 5, 'slow': 30} OOS=0.33 |
| GUI/信号回放 | PASS | 2 个回放点 |
| GUI/模拟盘建表 | PASS | 账户/持仓/成交/净值表就绪 |
| GUI/学习库向量入库 | PASS | docs 652→653 |
| GUI/合规审计(哈希链) | PASS | 链完整, 11 条 |
| GUI/股票大全索引 | PASS | 18331 只 |
| GUI/产业图谱 | WARN | 在线源不可达:ConnectionError（东财接口受网络限制；24h缓存机制已内置） |
| GUI/Swarm估值 | PASS | 3任务×3Agent+辩论对齐产出 |
| GUI/合规监控规则 | PASS | 荐股拦截=True, 中性放行=True |
| GUI/风控(VaR/压力) | PASS | VaR/压力测试产出 |
| GUI/协作空间 | PASS | 38 个工作区 |
| GUI/GDPR导出/删除 | PASS | (True, True) |
| GUI/i18n中英切换 | PASS | ('Shuying · Insight', '疏影 · 知微') |
| GUI/明暗主题切换 | PASS | ('dark', 'light') |
| GUI/命令面板 | PASS | 18331 条, 对话框就绪 |
| GUI/单实例锁 | PASS | 首次=True 二次=False |
| 服务/Web(FastAPI)路由 | PASS | ['/', '/api/analysis/{code}', '/api/backtest', '/api/bars/{code}', '/api/portfolio', '/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/ws/analysis'] |
| 服务/每日简报 | PASS | 112 字符 |
| 服务/更新检查(GitHub) | PASS | latest=v0.7.0 |