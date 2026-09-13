# -*- coding: utf-8 -*-
"""把分析状态渲染成结构化中文 Markdown 报告。"""
from __future__ import annotations

from core.agents.prompts import MARKET_NAME
from core.config import DISCLAIMER

STANCE_ICON = {"强烈看多": "🟩🟩", "看多": "🟩", "中性": "⬜", "看空": "🟥", "强烈看空": "🟥🟥"}
SIG_LABEL = {"technical": "技术面", "fundamental": "基本面", "news": "新闻面", "sentiment": "情绪面"}


def _kv(d: dict, sep: str = "=") -> str:
    """{MA5: 319.8} → 'MA5=319.8, MA10=...'，None 显示 —。"""
    if not d:
        return "—"
    parts = []
    for k, v in d.items():
        parts.append(f"{k}{sep}{'—' if v is None else v}")
    return ", ".join(parts)


def _bullets(items: list[str], limit: int | None = None) -> str:
    items = [x for x in (items or []) if x]
    if limit:
        items = items[:limit]
    return "\n".join(f"- {x}" for x in items) or "- （无）"


def render(state: dict) -> str:
    f = state.get("final", {})
    q = state.get("quote", {})
    ticker = state.get("ticker", "")
    name = state.get("name") or ticker
    market = MARKET_NAME.get(state.get("market"), state.get("market", ""))

    lines: list[str] = []
    lines.append(f"# {name}（{ticker}）AI 分析报告")
    lines.append(f"\n> {market} ｜ 数据截止 {state.get('asof')} ｜ 最新价 **{q.get('price')}** "
                 f"（{q.get('chg_pct')}%）｜ 生成于 {state.get('started_at', '')[:16].replace('T', ' ')}")

    # ---- 最终结论 ----
    lines.append("\n## 一、最终结论")
    lines.append(f"\n**操作评级：{f.get('action', '—')}**　置信度 {f.get('confidence', '—')}%　"
                 f"建议仓位 {f.get('position_pct', 0)}%")
    conf = f.get("confidence")
    if isinstance(conf, (int, float)):
        if conf < 40:
            lines.append(f"\n> ⚠️ 置信度偏低（{conf}%<40）：信号不明确，按风控原则不据此操作，建议观望。")
        elif conf < 60:
            lines.append(f"\n> 置信度中等（{conf}%）：可小仓位试错，严格止损。")
    if f.get("summary"):
        lines.append(f"\n{f['summary']}")

    scenarios = f.get("scenarios", [])
    if scenarios:
        lines.append("\n### 情景推演")
        lines.append("| 情景 | 概率 | 目标价 | 触发条件 |")
        lines.append("|---|---|---|---|")
        for s in scenarios:
            lines.append(f"| {s.get('label')} | {s.get('prob_pct')}% | "
                         f"{s.get('price_target', '—')} | {s.get('condition', '')} |")

    # ---- 操作方案 ----
    lines.append("\n## 二、操作方案")
    lines.append(f"\n- 建议周期：{f.get('horizon') or '—'}")
    lines.append(f"- 入场条件：{f.get('entry') or '—'}")
    lines.append(f"- 参考止损：{f.get('stop_loss') if f.get('stop_loss') is not None else '—'}")
    targets = f.get("targets") or []
    lines.append(f"- 目标价位：{', '.join(str(t) for t in targets) if targets else '—'}")
    lines.append(f"- 参考仓位：{f.get('position_pct', 0)}%（单标的，分批建仓）")

    # ---- 决策依据与风险 ----
    lines.append("\n## 三、核心依据")
    lines.append(_bullets(f.get("reasons"), 6))
    lines.append("\n## 四、风险提示")
    lines.append(_bullets(f.get("risks"), 8))

    # ---- 各分析师 ----
    lines.append("\n## 五、分析师团队观点")
    for key, label in SIG_LABEL.items():
        s = state.get("signals", {}).get(key)
        if not s:
            continue
        lines.append(f"\n### {STANCE_ICON.get(s.get('stance'), '')} {label}：{s.get('stance')}"
                     f"（置信 {s.get('confidence')}%）")
        if s.get("view"):
            lines.append(f"\n{s['view']}")
        if s.get("key_points"):
            lines.append("\n要点：")
            lines.append(_bullets(s["key_points"], 4))
        if s.get("risks"):
            lines.append("风险：")
            lines.append(_bullets(s["risks"], 3))

    # ---- 多空辩论 ----
    lines.append("\n## 六、多空辩论")
    lines.append("\n**多头论据：**")
    lines.append(_bullets(state.get("bull_case"), 5))
    lines.append("\n**空头论据：**")
    lines.append(_bullets(state.get("bear_case"), 5))

    # ---- 技术事实 ----
    tech = state.get("tech", {})
    if tech:
        lines.append("\n## 七、技术面事实（程序计算，非模型观点）")
        macd = tech.get("macd") or {}
        chg = tech.get("chg_pct_periods") or {}
        chg_txt = _kv({f"{k}日": (f"{v}%" if v is not None else None) for k, v in chg.items()})
        lines.append(f"\n- 均线：{_kv(tech.get('ma') or {})}")
        lines.append(f"- MACD：{_kv({k: v for k, v in macd.items() if k != 'signal'})}"
                     f"　形态：{macd.get('signal') or '无金叉/死叉'}")
        lines.append(f"- RSI14：{tech.get('rsi14')}　KDJ：{_kv(tech.get('kdj') or {})}")
        lines.append(f"- 布林：{_kv(tech.get('boll') or {})}　ATR14：{tech.get('atr14')}"
                     f"（{tech.get('atr14_pct')}%）")
        lines.append(f"- 区间涨跌：{chg_txt}　量比(5/20)：{tech.get('vol_ratio_5_20')}")
        lines.append(f"- 60日高/低：{tech.get('high_60d')} / {tech.get('low_60d')}，"
                     f"当前位于区间 {tech.get('pos_in_60d_pct')}%")

    # ---- 多因子 + 市场状态（程序计算，非模型观点）----
    factors = state.get("factors") or {}
    quant = state.get("quant") or {}
    if quant.get("score") is not None:
        lines.append(f"\n### 程序量化综合分：**{quant['score']}/100**（{quant.get('verdict','')}）")
        lines.append(f"- {quant.get('note', '')}")
    if factors:
        lines.append("\n## 七·补、多因子与市场状态（程序计算，非模型观点）")
        lines.append(f"\n- 多因子综合分：**{factors.get('composite')}/100**"
                     f"（{factors.get('consensus', '—')}）")
        for fname, fdata in (factors.get("factors") or {}).items():
            if isinstance(fdata, dict) and fdata.get("score") is not None:
                lines.append(f"  - {fname}：{fdata.get('note', '')}")
        reg = state.get("regime") or {}
        if reg:
            lines.append(f"- 市场状态：**{reg.get('regime')}**（{reg.get('note', '')}；"
                         f"风险预算系数 {reg.get('position_multiplier')}）")
    # ML 集成信号（随机森林，纯本地）
    ml = state.get("ml") or {}
    if ml and ml.get("up_prob") is not None:
        lines.append(f"\n### ML 集成信号（随机森林，{ml.get('n_samples')}样本训练）")
        lines.append(f"- 未来5日上涨概率：**{ml['up_prob']*100:.0f}%**（{ml.get('signal','')}）")
        if ml.get("top_features"):
            lines.append("- 主要贡献因子：" + ", ".join(
                f"{k}({v})" for k, v in ml["top_features"]))
        lines.append(f"- 注：{ml.get('note', '')}")
    # FinBERT 本地金融情感
    sml = state.get("sentiment_ml") or {}
    if sml.get("n"):
        lines.append(f"\n### 本地FinBERT新闻情感（{sml.get('n')}条标题）")
        lines.append(f"- {sml.get('note', '')}；分布 {sml.get('counts', {})}")
    # Kronos K线预测
    kr = state.get("kronos") or {}
    if kr.get("up_pct") is not None:
        lines.append(f"\n### Kronos K线基础模型短期预测")
        lines.append(f"- {kr.get('note', '')}（{kr.get('direction','')}）")

    # ---- 相似历史形态 ----
    patterns = state.get("patterns") or []
    if patterns:
        lines.append("\n## 八、历史相似形态检索（程序计算，非模型观点）")
        lines.append("\n以最近 20 个交易日收益形态匹配全历史，下列为最相似的历史片段"
                     "及其**其后 10 个交易日**的真实表现：")
        lines.append("\n| 起始日 | 结束日 | 相似度 | 后10日涨跌 | 期间最大回撤 | 期间最大上涨 |")
        lines.append("|---|---|---|---|---|---|")
        for p in patterns:
            lines.append(f"| {p.get('start_date')} | {p.get('end_date')} "
                         f"| {p.get('similarity_pct')}% | {p.get('forward_ret_pct'):+.2f}% "
                         f"| {p.get('forward_dd_pct'):.2f}% | +{p.get('forward_max_up_pct'):.2f}% |")
        fws = [p["forward_ret_pct"] for p in patterns]
        avg = sum(fws) / len(fws)
        up = sum(1 for x in fws if x > 0) / len(fws) * 100
        lines.append(f"\n均值 {avg:+.2f}%，上涨占比 {up:.0f}%。"
                     "历史相似不保证未来重演，仅作统计参考。")

    # ---- 基本面 ----
    funda = state.get("funda") or {}
    if funda:
        lines.append("\n## 九、基本面资料")
        for k, v in funda.items():
            if v:
                lines.append(f"- {k}：{v}")

    # ---- 资讯 ----
    news = state.get("news", [])
    if news:
        lines.append("\n## 十、最新资讯")
        for n in news[:10]:
            lines.append(f"- [{n.get('published_at', '')}] {n.get('title', '')}"
                         f"（{n.get('source', '')}）")

    # ---- 成本 ----
    tokens = state.get("tokens") or {}
    if tokens:
        lines.append(f"\n---\n本次分析模型 {tokens.get('model')}，共耗 {tokens.get('total_tokens')} tokens，"
                     f"约 ¥{tokens.get('cost_cny')}。")
    lines.append(f"\n**免责声明：**{DISCLAIMER}")
    return "\n".join(lines)
