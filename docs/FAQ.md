# 常见问题

## Q: 需要API Key吗？
A: 基础功能（K线、指标、数据展示）不需要Key。AI分析功能需要配置DeepSeek API Key（https://platform.deepseek.com）。

## Q: 支持哪些股票？
A: A股（5914只）、港股（3385只）、美股（9028只），共18327只。

## Q: 数据从哪里来？
A: AKShare、yfinance、Tushare多源冗余，主源失败自动切换备源。

## Q: 为什么分析结果是[MOCK]？
A: 说明没有配置API Key，或API调用失败。检查.env中的DEEPSEEK_API_KEY。

## Q: 数据存在哪里？
A: 全部存在本地SQLite，不上传任何数据。

## Q: 支持Mac/Linux吗？
A: 源码版支持。一键版目前仅Windows。
