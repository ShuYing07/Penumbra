# FINOS 生态对接指南

FINOS（金融科技开源基金会，finos.org）正在推动金融行业开源协作，
参与项目包括 **FDC3**（桌面应用互操作标准）、**CALM**（云架构语言）、
**AI 治理框架（AIGF）**、**Fluxnova** 等。本文说明「疏影·知微」如何与
FINOS 标准对接，以获取企业级信任与生态反馈。

## 1. FDC3（桌面应用互操作）

FDC3 定义金融桌面应用间的上下文共享标准。本工具可在以下场景对接：

- **意图（Intents）**：注册 `ViewChart`、`AnalyzeInstrument` 等意图，
  供同桌面其他 FDC3 应用（如 Bloomberg 终端、内部 CRM）拉起本工具分析某标的。
- **上下文（Context）**：以 `fdc3.instrument` 上下文传递标的（`{type, id: {ticker}}`），
  实现跨应用"点到哪、分析到哪"。

对接建议：
```json
{
  "appId": "shuying-insight",
  "name": "疏影·知微",
  "intents": [
    {"name": "ViewChart", "displayName": "查看K线"},
    {"name": "AnalyzeInstrument", "displayName": "AI多空分析"}
  ],
  "contexts": ["fdc3.instrument"]
}
```
实现参考：`micro_frontend/`（模块接口）与 `web_ui/`（REST 暴露）可组合为
FDC3 Bridge。

## 2. CALM（云架构语言）

CALM 用声明式方式描述系统拓扑与安全边界。可将本工具的企业部署拓扑
（主程序 + FastAPI + SQLite/湖仓 + 私有化模型端点）建模为 CALM 蓝图，
输出为机器可读的架构图，便于合规审查（SOC 2 / ISO 27001 材料）。

## 3. AI 治理框架（AIGF）

AIGF 关注 AI 系统治理。本工具已具备的基础：

- **可解释性账本**：`security/audit_ledger.py`（哈希链，每次 AI 决策留痕）；
- **合规监控**：`compliance/continuous_monitor.py`（实时监测 + 人工审核队列）；
- **规则引擎**：`compliance/rule_engine.py`（企业自定义合规规则）；
- **数据主权**：`sovereign_agent/private_deployment.py`（数据不出企业边界）。

## 4. 加入 FINOS 的方式

1. 提交 CLA（贡献者许可协议）；
2. 通过 FINOS 社区邮件列表 / GitHub 发起对接讨论；
3. 将 FDC3 Bridge、CALM 蓝图等以独立模块开源（本项目 MIT 许可，可直接复用）。

## 5. 本项目的对标基线

| 能力 | 现状 | FINOS 对接后 |
|---|---|---|
| 桌面互操作 | PyQt 单机 | FDC3 意图/上下文共享 |
| 合规留痕 | 哈希链审计 | AIGF 治理框架对齐 |
| 企业部署 | Docker/私有化 | CALM 蓝图 + SOC2 材料 |
