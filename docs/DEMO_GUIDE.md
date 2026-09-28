# Demo 演示录制指引

一份 30 秒的 Demo GIF 是开源项目 README 的"门面"，能显著提升用户第一印象。本文档说明如何录制、压缩并替换 README 中的演示占位。

## 录制内容（30 秒脚本）

| 时间 | 动作 | 画面重点 |
|------|------|---------|
| 0-3s | 启动程序，自动加载示例（AAPL） | 界面从黑屏到 K 线出现 |
| 3-8s | 输入 `600519` 回车 | K 线切换到贵州茅台，右侧信息更新 |
| 8-18s | 点击"对话分析"，开始分析 | AI 报告流式输出（Markdown 渲染） |
| 18-25s | 切到"多空辩论" | 看多/看空结构化对抗（Claim 编号） |
| 25-30s | 切到"策略回测" | 净值曲线 vs 基准对比图 |

## 录制工具

- **Windows**：Windows + Alt + R（Xbox Game Bar）或 [ShareX](https://getsharex.com)（免费，支持直接导出 GIF）
- **macOS**：Shift + Cmd + 5 → 录屏
- **跨平台**：OBS Studio + [Gifski](https://github.com/sindresorhus/Gifski)（高质量 GIF 转换）

## 压缩要求

- 时长 ≤ 30 秒
- 文件 ≤ 5MB（GitHub 限制；超过 1MB 用 [Ezgif](https://ezgif.com) 压缩）
- 分辨率 1280×720 或更低

## 替换占位

1. 将 GIF 命名为 `demo.gif` 放入 `docs/`；
2. 打开 `README.md`，找到 `![Demo](docs/demo.gif)` 占位行，替换为真实引用：
   ```markdown
   ![Demo](docs/demo.gif)
   ```
3. 提交并 push，GitHub 会自动渲染。

## 常见问题

- **GIF 太大**：用 Ezgif 降帧率（10fps）或裁剪分辨率；
- **录制卡顿**：关闭动画效果（系统设置→视觉特效→最佳性能），录制前先跑一次让数据预热；
- **文字看不清**：录制时放大窗口（Ctrl + 滚轮）或提高系统 DPI。
