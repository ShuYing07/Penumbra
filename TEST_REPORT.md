# 测试报告（TEST_REPORT）

版本：疏影 · 知微（Penumbra）　日期：2026-09-14

## 一、自动化测试（test_all.py）
全部 **10/10 通过**：

| 模块 | 结果 |
|---|---|
| 数据-日线（SH600519，OHLCV 列齐全） | ✅ |
| 数据-实时价（休市兜底为收盘） | ✅ |
| 技术指标（RSI/MACD/KDJ/BOLL） | ✅ |
| 合规过滤（买入/目标价→【已过滤】） | ✅ |
| 多空辩论模块可导入 | ✅ |
| 回测引擎（total/maxdd/sharpe/winrate） | ✅ |
| 产业图谱（按股/按概念） | ✅ |
| 本地 AI 检测 | ✅ |
| 配置 API Key 读取 | ✅ |
| .env.example 完整性 | ✅ |

另：原有单元测试 **11/11** 通过。

## 二、本轮发现并修复的 Bug
1. **no such table: daily_bars** —— 全新安装首次访问数据库未建表。修复：连接时自动幂等建表。
2. **休市实时价显示 0 / -100%** —— 盘口为空未兜底。修复：自动用最新日线收盘兜底。
3. **图标未打进 exe** —— PyInstaller 漏收 assets。修复：spec 加入 assets，并兼容 `sys._MEIPASS`。
4. **首次启动 NameError** —— welcome 函数定义顺序问题。修复：前移到 main 之前。
5. 新增 `core/compliance.py` 的 `sanitize_ai_output`，统一过滤荐股敏感词并追加免责声明。

## 三、开源文件完整性
- 根目录合规文件 9/9 齐备；`.github` 7 项齐备（本轮补 `compliance_check.yml`）。
- DISCLAIMER 含"不构成投资建议/不具备业务资格/用户自担风险"；PRIVACY 补 GDPR/CCPA 说明；LICENSE 为 MIT，版权署名 ShuYing07。
- `.env`（真实 Key）已被 gitignore，未入库。

## 四、手动测试
见 `MANUAL_TEST_CHECKLIST.md`，由发布前人工逐项打勾。

## 五、打包
- 已用 PyInstaller onedir 打包，`dist\StockAIPredictor\疏影知微.exe` offscreen 启动存活。
- `build_exe.bat` 已生成（按要求未自动运行，供手动）。

## 六、结论
自动化层面达到开源发布标准；GUI 交互项请按 MANUAL_TEST_CHECKLIST 人工确认后再 push。
