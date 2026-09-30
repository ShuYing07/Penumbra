# QuestDB 时序存储评估（模块三 · 参考 Brevan Howard 选型）

> 结论先行：**当前阶段不替换 SQLite**，保留 SQLite 作为主存储，
> QuestDB 作为可选的时序分析旁路（旁挂模式）。理由见下。

## 背景

Brevan Howard（全球最大对冲基金之一）选择 QuestDB 作为系统性市场数据平台，
配合 Aeron（低延迟传输）、Polars（数据帧层）、Grafana（仪表盘）。
QuestDB 是开源时序数据库，专为资本市场设计：高摄取吞吐、列式存储、
SQL 扩展（`SAMPLE BY` / `ASOF JOIN`）。

## 评估维度

| 维度 | SQLite（现状） | QuestDB（候选） | 结论 |
|---|---|---|---|
| 摄取吞吐 | ~1 万行/秒（单写锁） | 100 万+ 行/秒（列式 + 批量） | QuestDB 优，但当前单机数据量 <1GB/年 |
| 查询延迟（日线 K 线 6000 行） | 毫秒级（内存缓存） | 毫秒级 | 打平 |
| 时间窗口聚合 | 需手动 GROUP BY | `SAMPLE BY` 原生 | QuestDB 优（但可用 pandas 等效） |
| 部署复杂度 | 零（内嵌库） | 需独立服务 + 端口 + 运维 | SQLite 优 |
| 依赖体积 | 无新增 | ~200MB JVM/二进制 | SQLite 优 |
| 离线/单机友好 | 完美 | 需常驻进程 | SQLite 优 |

## 决策

- **保留 SQLite 为主存储**：数据规模（1.8 万标的 × 日线 × 数年 ≈ 数 GB 以内）
  SQLite + 内存缓存完全胜任；零运维、随程序分发是桌面应用的关键约束。
- **QuestDB 旁挂（可选）**：当用户未来需要
  - 秒级 tick 历史回放（>1000 万行）；
  - 多标的 ASOF JOIN（事件研究）；
  - Grafana 实时仪表盘
  时，可启动 QuestDB 旁挂实例，由 `core/realtime_engine.py` 双写
  （SQLite 快照 + QuestDB 明细），不影响主流程。
- **Polars 数据帧**：仅在大数据框聚合场景（板块/全市场筛选）可替换
  pandas，属可选优化，不引入默认依赖。

## 落地计划（未来轮次）

1. 用户确认数据规模增长到 tick 级后，新增 `core/storage/questdb_writer.py`；
2. 提供 docker-compose 一键旁挂；
3. 迁移策略：SQLite 仍为权威源，QuestDB 只读分析副本。
