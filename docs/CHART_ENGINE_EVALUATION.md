# 高级金融图表引擎评估（模块六）

> 结论先行：**不替换引擎**。继续使用 PyQtGraph 作为主渲染引擎，QWebEngineView
> 仅作为可选旁挂（本地 HTML/JS 图表嵌入，如未来集成 AG Charts/Highcharts 时）。
> 增量能力（Gann/Pitchfork/谐波/艾略特波浪绘图、多图表同步、tick 回放）
> 以纯 Python 核心 + PyQtGraph 渲染层实现，零新依赖、可单测。

## 一、候选方案对比

| 方案 | 渲染 | 绘图工具 | 500k 点 | 依赖 | 集成成本 | 结论 |
|---|---|---|---|---|---|---|
| PyQtGraph（现行） | QPainter 硬件加速 | 自绘工具栏已有 4 种 + 右键/收藏/磁吸/持久化 | 万级日线绰绰有余（tick 级需抽稀） | 已在用 | 0 | **保留为主引擎** |
| QWebEngineView + VNInvestCharts | WebGL/Canvas | 76 种专业工具 | 500k+ | 引入 QWebEngine + 前端包 | 高：双栈渲染、通信桥、跨进程状态同步 | 可选旁挂，非必须 |
| QWebEngineView + AG Charts / Highcharts | WebGL（Boost） | 基础 K 线/OHLC | 500k+ | 同上 | 高 | 同上 |
| CandleKit（TradingView LW Charts 扩展） | Canvas | 趋势线/斐波/矩形/回放 | 高 | 前端包 + 桥 | 中高 | 若未来走纯 Web UI 再考虑 |

## 二、为什么保留 PyQtGraph（本轮决策依据）

1. **当前数据量级**：日线级（每标的数百~数千根），PyQtGraph 渲染无压力；
   tick 级回放由 playback.py 在数据层抽稀/步进，渲染仍走 PyQtGraph。
2. **既有功能已对齐 TradingView 基本盘**：绘图工具栏（趋势线/水平线/斐波那契/矩形）
   + 磁吸吸附 + 收藏 + 右键样式 + SQLite 持久化，均在 chart_tab 落地。
3. **零新依赖**符合项目红线（新依赖需用户手动装）；QWebEngineView 体积大、
   启动慢，与「性能瘦身、exe≤300MB」目标冲突。
4. 未来若用户明确要 Web 端图表（浏览器访问），再评估 QWebEngine+AG Charts，
   架构上保留 `chart_tab` 与渲染解耦的余地（绘图数据统一走 core/drawings.py）。

## 三、本轮新增（实现于模块六）

1. **高级绘图工具** `core/drawings_advanced.py`：
   - Gann 角度线：1x1（45°基准）/ 1x2 / 2x1 角度与锚点计算；
   - Andrew's Pitchfork：中位线 + 上下通道（三点定位）；
   - 谐波形态：AB=CD 对称 / XABCD 关键位（0.618/0.786/1.272/1.618）；
   - 艾略特波浪：基于最近 5 段折返投影第 5 浪目标位。
   全部纯数学函数，`__main__` 自检断言通过。
2. **tick 级回放** `core/quant/playback.py`：
   - `PlaybackEngine(bars, tick_ratio)`：将日线插值生成 tick 序列（确定性）；
   - 播放/暂停、步进 ±1、速度控制（1x/2x/4x/8x）、跳转；
   - 回调通知当前 bar 索引，供 UI 高亮。
3. **多图表同步** `core/chart_sync.py`：轻量事件总线（QObject 信号桥接层，
   同标的跨标签页十字光标/区间联动；无 GUI 时退化为纯 Python 观察者）。

## 四、已知限制（诚实披露）

- tick 级回放为**合成 tick**（按 OHLCV 插值），非交易所原始逐笔；用于策略
  演示/教学可，用于高频验证不足。
- 多图表同步当前为同进程内联动；跨进程（Web 端）需另行实现。
- 500k+ 数据点若未来出现，PyQtGraph 需降采样（min/max 抽稀），当前未触发。
