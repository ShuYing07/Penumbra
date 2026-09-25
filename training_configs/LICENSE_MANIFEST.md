# 教学资源许可证清单（StockAIPredictor 蒸馏数据来源）

> 仅用于本地离线训练（SFT 教师语料），不分发模型权重，不商用。
> 所有资源均为显式开放许可或官方公开投教材料。抓取时记录日期与原始哈希。

## 内置源（2026-09-11 核实）

| id | 来源 | URL | 类型 | 许可 | 语言 | 主题 |
|---|---|---|---|---|---|---|
| wiki_stock_zh | 维基百科 - 股票 | https://zh.wikipedia.org/wiki/股票 | html | CC-BY-SA | zh | fundamental |
| wiki_ta_zh | 维基百科 - 技术分析 | https://zh.wikipedia.org/wiki/技术分析 | html | CC-BY-SA | zh | technical |
| wiki_macro_zh | 维基百科 - 宏观经济学 | https://zh.wikipedia.org/wiki/宏观经济学 | html | CC-BY-SA | zh | macro |
| wiki_stock_en | Wikipedia - Stock | https://en.wikipedia.org/wiki/Stock | html | CC-BY-SA | en | fundamental |
| wiki_ta_en | Wikipedia - Technical analysis | https://en.wikipedia.org/wiki/Technical_analysis | html | CC-BY-SA | en | technical |
| wiki_macd_en | Wikipedia - MACD | https://en.wikipedia.org/wiki/MACD | html | CC-BY-SA | en | technical |
| wiki_rsi_en | Wikipedia - RSI | https://en.wikipedia.org/wiki/Relative_strength_index | html | CC-BY-SA | en | technical |
| wiki_risk_en | Wikipedia - Risk management | https://en.wikipedia.org/wiki/Risk_management | html | CC-BY-SA | en | risk |
| imf_glossary | IMF - 金融词汇表 | https://www.imf.org/external/pubs/ft/terms.htm | html | Educational Use | en | macro/fundamental |
| ecb_edu | ECB - 货币政策教育 | https://www.ecb.europa.eu/ecb/educational/html/index.en.html | html | Educational Use | en | macro |
| bis_investor | BIS - 投资者教育 | https://www.bis.org/publ/educational.htm | html | Educational Use | en | macro/risk |
| csrc_risk_edu | 证监会 - 风险警示投教 | https://www.csrc.gov.cn/pub/newsite/tzzjy/tzzcs/tzfxsj/ | html | Educational Use | zh | risk |
| csc_sse_edu | 上交所 - 投资者教育 | https://edu.sse.com.cn/col/col5413/index.html | html | Educational Use | zh | fundamental/risk |

## 已弃用源（核实失败）
| id | 原因 | 日期 |
|---|---|---|
| investopedia_* (5 个) | Cloudflare 反爬 403，换用 Wikipedia 同主题词条 | 2026-09-11 |
| pbc_fin_edu | URL 路径 404（人行官网结构调整），已移除 | 2026-09-11 |

## 扩展规则
- 新增源须在此表登记 URL/许可证/抓取日期；
- 只收 CC-BY / CC-BY-SA / CC0 / Public Domain / 官方投教公开材料；
- 不碰盗版电子书、付费教材、明确禁止再分发的内容；
- 产物仅本地训练，权重不外传。

## 抓取记录
- 2026-09-11：csrc_risk_edu 成功 26775 字符；wiki_stock_zh 9599；wiki_stock_en 43050；wiki_ta_en 57580（共 4 文件 169445 字符）
