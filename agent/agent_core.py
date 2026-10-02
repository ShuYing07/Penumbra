# -*- coding: utf-8 -*-
"""AgentCore：AI Agent 工具调用循环（意图驱动 → 顺序工具链 → 结果注入 → 合规输出）。

设计参考：
- OpenBB Copilot：sequential tool usage（先行情→再指标→再新闻→综合报告）
- iFinD MCP：自然语言即查询，LLM 理解工具语义
- 合规红线：所有输出先过 RuleEngine 过滤，命中即降级/标注，绝不输出投资建议

三层意图解析（保证离线可用 + 在线更强）：
1. 规则层：正则/关键词 → 工具序列（确定性、零成本）
2. LLM 层：规则未命中且有 API Key 时，让 LLM 选工具（mock 时跳过）
3. 兜底层：无法解析 → 明确反馈"请换个说法"
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Dict, List

from agent.schemas import ToolResult
from agent.tool_defs import build_registry, call_tool
from compliance.rule_engine import RuleEngine

log = logging.getLogger("stockai.agent.core")

# 常见别名（拼音缩写/俗称 → 标准代码）
_ALIASES = {
    "gzmt": "SH600519", "茅台": "SH600519", "moutai": "SH600519",
    "nfts": "SZ300750", "宁德": "SZ300750", "宁德时代": "SZ300750",
    "catl": "SZ300750",
    "tencent": "0700.HK", "腾讯": "0700.HK", "腾讯控股": "0700.HK",
    "aapl": "AAPL", "苹果": "AAPL", "apple": "AAPL",
    "hs300": "SH000300", "沪深300": "SH000300", "沪深三百": "SH000300",
    "szzs": "SH000001", "上证": "SH000001", "上证指数": "SH000001",
    "cyb": "SZ399006", "创业板": "SZ399006", "创业板指": "SZ399006",
    "shenzhen": "SZ399001", "深证": "SZ399001", "深证成指": "SZ399001",
}

_TICKER_RE = re.compile(r"(?:SH|SZ)?\d{6}|\d{4}\.HK|[A-Z]{1,5}\.?[A-Z]{0,2}(?:\.HK)?|AAPL")


def extract_ticker(text: str) -> str | None:
    """从自然语言里提取股票代码。"""
    t = text.strip()
    up = t.upper()
    # 1) 别名表（包含匹配：'分析 茅台' → 茅台 → SH600519）
    low = up.lower().replace(" ", "")
    for k, v in _ALIASES.items():
        if k in low:
            return v
    if up in _ALIASES:
        return _ALIASES[up]
    # 2) 索引精确匹配（名称/代码）
    try:
        from agent.tool_defs import _stocks_index
        from core.data.service import normalize_ticker
        for s in _stocks_index():
            if up == s["code"] or up == s["name"].upper() or up == s["name"]:
                return normalize_ticker(s["code"])
    except Exception:  # noqa: BLE001
        pass
    # 3) 代码正则
    m = _TICKER_RE.search(up)
    if m:
        from core.data.service import normalize_ticker
        try:
            return normalize_ticker(m.group(0))
        except Exception:  # noqa: BLE001
            return m.group(0)
    return None


class AgentCore:
    """工具调用 Agent 核心（线程安全，可复用于 GUI/API/MCP）。"""

    def __init__(self, llm=None, mock: bool | None = None):
        self._lock = threading.Lock()
        self.tools = build_registry()
        self.llm = llm
        self.rules = RuleEngine()
        if mock is None:
            mock = _is_mock_env()
        self.mock = mock
        # 模型名（审计留痕用，模块六）
        self.model_name = ""
        if llm is not None:
            self.model_name = (getattr(llm, "model", None)
                               or getattr(llm, "model_name", None)
                               or getattr(type(llm), "__name__", "") or "")
        # 模块七：推理事件流（可观测性）
        from agent.agent_events import EventCollector
        self.events = EventCollector()
        self._last_review_id: str | None = None

    def set_event_callback(self, cb) -> None:
        """注册事件回调（如 PyQt 信号桥），实时推送 THINKING/TOOL_CALL/…。"""
        self.events.set_callback(cb)

    # ---------------- 意图解析 ----------------
    def plan(self, text: str) -> List[Dict[str, Any]]:
        """把自然语言解析为有序工具调用计划 [{tool, kwargs}]。"""
        low = text.lower()
        ticker = extract_ticker(text)

        # 市场/大盘
        if any(k in low for k in ("大盘", "市场概览", "今日市场", "市场怎么样", "行情如何")):
            return [{"tool": "get_market_overview", "kwargs": {}}]

        # 回测
        if "回测" in low:
            kw = {}
            for s in ("ma_cross", "rsi_reversion", "macd_cross", "buy_hold"):
                if s in low:
                    kw["strategy"] = s
                    break
            if ticker:
                kw["code"] = ticker
                return [{"tool": "run_backtest", "kwargs": kw}]
            return [{"tool": "run_backtest", "kwargs": kw}]

        # 新闻
        if any(k in low for k in ("新闻", "资讯", "消息面", "最近消息")):
            if ticker:
                return [{"tool": "search_news", "kwargs": {"code": ticker}}]
            return [{"tool": "get_market_overview", "kwargs": {}}]

        # 实时快照
        if any(k in low for k in ("实时", "现价", "最新价", "盘中")):
            if ticker:
                return [{"tool": "get_realtime_snapshot", "kwargs": {"code": ticker}}]

        # 搜索股票
        if any(k in low for k in ("搜索", "查找", "找一下", "搜一下", "有哪些")):
            q = re.sub(r"(帮我|请|搜索|查找|找一下|搜一下)", "", text).strip()
            return [{"tool": "search_stocks", "kwargs": {"query": q or text}}]

        # 筛选（自然语言转条件，模块四引擎）
        if any(k in low for k in ("筛选", "市盈率", "股息率", "低于", "高于", "银行股", "板块")):
            from agent.screener_parser import parse_nl_to_conditions
            conds = parse_nl_to_conditions(text)
            return [{"tool": "run_screener", "kwargs": conds}]

        # 分析个股（顺序工具链：行情 → 指标 → 新闻 → 报告）
        if ticker:
            plan = [
                {"tool": "fetch_stock_data", "kwargs": {"code": ticker}},
                {"tool": "calculate_indicators", "kwargs": {"code": ticker}},
            ]
            if any(k in low for k in ("新闻", "消息", "基本面", "全面", "深入")):
                plan.append({"tool": "search_news", "kwargs": {"code": ticker}})
            if any(k in low for k in ("回测", "验证", "历史表现", "策略")):
                plan.append({"tool": "run_backtest",
                             "kwargs": {"code": ticker, "strategy": "ma_cross"}})
            return plan

        # 纯代码输入（chat_tab 会走原链路，这里兜底）
        if ticker:
            return [{"tool": "fetch_stock_data", "kwargs": {"code": ticker}}]

        # LLM 兜底（规则未命中；mock 或未配置 key 时给出友好引导）
        if not self.mock and self.llm is not None:
            return self._llm_plan(text)
        return []

    def _llm_plan(self, text: str) -> List[Dict[str, Any]]:
        """LLM 意图→工具选择（OpenAI 兼容）。失败回退空计划。"""
        try:
            names = list(self.tools.keys())
            desc = "\n".join(f"- {n}: {self.tools[n]['description'][:80]}" for n in names)
            prompt = (
                f"可用工具：\n{desc}\n\n"
                f"用户说：{text}\n\n"
                f"请输出要依次调用的工具名 JSON 数组（如 [\"fetch_stock_data\"]），"
                f"只输出 JSON。")
            raw = self._chat_text(prompt)
            m = re.search(r"\[.*?\]", raw, re.S)
            if not m:
                return []
            plan_names = json.loads(m.group(0))
            return [{"tool": n, "kwargs": {}} for n in plan_names if n in self.tools]
        except Exception as e:  # noqa: BLE001
            log.warning("LLM 意图解析失败：%s", e)
            return []

    # ---------------- 执行 ----------------
    def _chat_text(self, prompt: str) -> str:
        """调 LLMRunner 原始文本（raw=True 直接返回 content 字符串）。"""
        if self.llm is None:
            return ""
        out = self.llm.chat_json(node="agent", system="", user=prompt, raw=True)
        return out if isinstance(out, str) else str(out)

    def run(self, user_input: str,
            context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """完整循环：计划 → 顺序执行 → 注入结果 → 生成回复 → 合规过滤 → 记录。

        context 可选：{page, stock, skill, history}，按优先级注入 LLM Prompt。
        返回含 events（推理轨迹，模块七可观测性）。
        """
        from agent.agent_events import EventType
        plan = self.plan(user_input)
        self.events.emit(EventType.THINKING,
                         f"解析意图完成：共 {len(plan)} 步工具链"
                         + (f"（{ ' → '.join(s['tool'] for s in plan) }）" if plan else ""))
        results: List[Dict[str, Any]] = []
        for step in plan:
            self.events.emit(EventType.TOOL_CALL,
                             f"调用 {step['tool']}",
                             tool=step["tool"], kwargs=step.get("kwargs") or {})
            res = call_tool(step["tool"], dict(step.get("kwargs") or {}))
            d = res.model_dump()
            ok = d.get("ok")
            note = d.get("note", "")
            self.events.emit(EventType.TOOL_RESULT,
                             f"{step['tool']} → {'成功' if ok else '失败'} "
                             + (f"（{note[:80]}）" if note else ""),
                             ok=ok, tool=step["tool"])
            results.append({"tool": step["tool"], "result": d})
        self.events.emit(EventType.REASONING, "基于工具结果组织最终回复")
        answer = self._compose(user_input, plan, results, context)
        # 合规过滤（命中红线 → 追加免责标注）
        violations = self.rules.check({"text": answer})
        compliance = {
            "blocked": self.rules.is_blocked(violations),
            "violations": [v["detail"] for v in violations],
        }
        if compliance["blocked"]:
            answer += "\n\n⚠️ 检测到敏感话术，已按合规规则标注，输出仅供参考，不构成投资建议。"
        # AI 评审员（输出前独立审核：承诺收益/无风险/荐股/内幕/免责声明）
        try:
            from security.ai_reviewer import review_output
            review = review_output(answer)
            compliance["ai_review"] = {
                "passed": review["passed"], "score": review["score"],
                "issues": [f"{i['label']}:{i['keyword']}" for i in review["issues"]],
                "disclaimer_ok": review["disclaimer_ok"],
            }
            if not review["passed"]:
                answer += (f"\n\n🔎 合规评审：{review['score']}/100，"
                           f"提示 {len(review['issues'])} 项（{'、'.join(i['label'] for i in review['issues'][:3])}），"
                           f"输出仅供参考，不构成投资建议。")
        except Exception as e:  # noqa: BLE001
            log.debug("AI 评审员不可用：%s", e)
        self.events.emit(EventType.FINAL_REPORT, "报告已生成", blocked=compliance["blocked"])
        # 记录到决策日志
        self._log_decision(user_input, plan, results, answer, compliance)
        # 模块七：推理轨迹持久化（可解释性账本）
        try:
            from agent.agent_trace_store import save_trace
            import hashlib
            aid = hashlib.md5(f"{user_input}|{time.time()}".encode()).hexdigest()[:16]
            save_trace(aid, self.events.snapshot())
        except Exception as e:  # noqa: BLE001
            log.debug("trace 持久化失败：%s", e)
        # 模块八：数据溯源（工具结果快照登记为证据）
        try:
            import uuid
            from core.evidence_manager import save_report_evidence
            _aid = f"agent|{uuid.uuid4().hex[:12]}"
            save_report_evidence(_aid, {
                "ticker": extract_ticker(user_input) or "—",
                "quote": next((r["result"].get("data") or {} for r in results
                               if r["tool"] == "fetch_stock_data"), {}),
                "signals": {},
                "bull_case": [], "bear_case": [],
                "trader": {}, "risk": {},
                "final": {"action": "分析完成", "summary": answer[:300]},
            })
        except Exception as e:  # noqa: BLE001
            _aid = None
            log.debug("证据链登记失败：%s", e)
        return {
            "plan": [{"tool": s["tool"], "kwargs": s["kwargs"]} for s in plan],
            "results": results,
            "answer": answer,
            "compliance": compliance,
            "events": self.events.snapshot(),
            "evidence_id": _aid,  # 供 UI 🔗 证据链回溯
        }

    # ---------------- 回复合成 ----------------
    def _compose(self, user_input: str, plan, results,
                 context: Dict[str, Any] | None = None) -> str:
        if not plan:
            return ("我暂时没理解你的意图。可以试试：\n"
                    "· 「分析 600519」→ 行情+指标报告\n"
                    "· 「回测 AAPL ma_cross」→ 策略回测\n"
                    "· 「茅台最近有什么新闻」→ 资讯\n"
                    "· 「搜索 银行股」→ 股票检索\n"
                    "· 「今日市场概览」→ 大盘速览")
        if not self.mock and self.llm is not None:
            return self._llm_compose(user_input, results, context)
        return self._mock_compose(user_input, results)

    def _mock_compose(self, user_input: str, results) -> str:
        """离线模板合成（客观数值直述，不编造结论）。"""
        lines = [f"<b>分析完成</b>（离线模式）"]
        for item in results:
            r = item["result"]
            if not r.get("ok"):
                lines.append(f"· {r['tool']}：<span style='color:#FF1744'>失败 {r.get('note','')}</span>")
                continue
            data = r.get("data") or {}
            if r["tool"] == "fetch_stock_data":
                chg = data.get("chg_pct_1d")
                chg_txt = f"{chg:+.2f}%" if chg is not None else "—"
                col = "#00C853" if (chg or 0) >= 0 else "#FF1744"
                lines.append(
                    f"· {data['code']}（{data['market']}）最新收盘 <b>{data.get('close')}</b>"
                    f"（<span style='color:{col}'>{chg_txt}</span>，源：{data.get('source')}）")
                if data.get("rsi14") is not None:
                    lines.append(f"· RSI(14) = {data['rsi14']:.1f}；MACD：{data.get('macd_signal')}")
            elif r["tool"] == "calculate_indicators":
                vals = data.get("values") or {}
                parts = [f"{k}={v}" for k, v in vals.items() if not str(v).startswith("error")]
                lines.append(f"· 技术指标：{'；'.join(parts)}")
            elif r["tool"] == "search_news":
                items = (data.get("items") or [])
                lines.append(f"· 最近新闻 {len(items)} 条：")
                for n in items[:5]:
                    lines.append(f"　· {n.get('title','')}（{n.get('source','')}）")
                if not items:
                    lines.append("　（暂无新闻）")
            elif r["tool"] == "run_backtest":
                m = data.get("metrics") or {}
                lines.append(
                    f"· 回测({data.get('strategy')})：收益 {m.get('total_return_pct')}%，"
                    f"年化 {m.get('annual_return_pct')}%，最大回撤 {m.get('max_drawdown_pct')}%，"
                    f"夏普 {m.get('sharpe')}，胜率 {m.get('win_rate_pct')}%")
            elif r["tool"] == "get_market_overview":
                for ix in (data.get("indices") or []):
                    c = "#00C853" if (ix.get("chg_pct") or 0) >= 0 else "#FF1744"
                    lines.append(f"· {ix['name']} {ix['price']}（<span style='color:{c}'>{ix['chg_pct']:+.2f}%</span>）")
            elif r["tool"] == "search_stocks":
                hits = data.get("hits") or []
                lines.append("· 搜索结果：")
                for h in hits[:10]:
                    lines.append(f"　· {h['name']}（{h['code']}，{h['market']}）")
                if not hits:
                    lines.append("　（无匹配）")
            elif r["tool"] == "run_screener":
                hits = data.get("hits") or []
                lines.append(f"· 筛选到 {len(hits)} 只：")
                for h in hits[:10]:
                    lines.append(f"　· {h.get('name','')}（{h.get('code','')}）{h.get('price','')}")
            elif r["tool"] == "get_realtime_snapshot":
                lines.append(f"· 实时：{data}")
        lines.append("<br/>以上均为客观数据展示，不构成投资建议。")
        return "<br/>".join(lines)

    def _llm_compose(self, user_input: str, results,
                     context: Dict[str, Any] | None = None) -> str:
        try:
            from skill_loader import skills_prompt
            from context_manager import build_context_block
            payload = json.dumps(
                [{"tool": r["tool"], "result": r["result"]} for r in results],
                ensure_ascii=False, default=str)
            skill = skills_prompt(user_input)
            ctx = build_context_block(
                user_input,
                page=(context or {}).get("page"),
                stock=(context or {}).get("stock"),
                skill=(context or {}).get("skill"),
                history=(context or {}).get("history"))
            # 蒸馏知识注入：检索与请求相关的本地金融知识（含边界提醒），
            # 失败静默降级（不影响主流程）。
            kb_ctx = ""
            try:
                from core.knowledge_distiller import distill_context
                kb_ctx = distill_context(user_input, limit=3)
            except Exception:  # noqa: BLE001
                pass
            prompt = (
                f"你是疏影·知微的AI研究助手。{skill}\n\n"
                f"用户说：{user_input}\n\n"
                f"{ctx}\n\n"
                f"{kb_ctx}\n\n"
                f"工具执行结果如下：\n{payload}\n\n"
                f"请按技能指令与简洁中文组织回答（3-6条要点），只陈述客观数据，"
                f"不得给出买入/卖出/目标价等投资建议。")
            return self._chat_text(prompt)
        except Exception as e:  # noqa: BLE001
            log.warning("LLM 合成失败，回退模板：%s", e)
            return self._mock_compose(user_input, results)

    # ---------------- 记忆 ----------------
    def _log_decision(self, user_input, plan, results, answer, compliance) -> None:
        """写入审计链（AI 输出留痕，含模型/合规过滤结果）+ 长期记忆。"""
        try:
            from security.audit_ledger import append
            plan_txt = "→".join(s["tool"] for s in plan) or "none"
            model = getattr(self, "model_name", None) or ""
            review = compliance.get("ai_review") or {}
            append(actor="ai", action="agent_analysis",
                   detail=(f"[{plan_txt}] 模型={model} "
                           f"评审={review.get('score', '—')}/100 "
                           f"通过={review.get('passed', '—')} :: "
                           f"{user_input[:60]} :: {answer[:100]}"))
        except Exception as e:  # noqa: BLE001
            log.debug("审计写入失败：%s", e)
        # 长期记忆（模块二 Human-in-the-loop）：
        #   strict 模式：未经人类审校不得写入知识库；
        #   auto 模式（默认）：自动写入并同时创建审校记录供 UI 审校。
        try:
            from core.human_review import ReviewGate
            from core.memory.long_term import save_analysis
            ticker = extract_ticker(user_input) or ""
            price = None
            for r in results:
                d = (r.get("result") or {}).get("data") or {}
                if r["tool"] == "fetch_stock_data" and d.get("close") is not None:
                    price = float(d["close"])
                    break
            if ticker and price is not None:
                gate = ReviewGate()
                rec = gate.create(answer, {"ticker": ticker,
                                           "trigger": user_input[:60]})
                strict = _review_mode() == "strict"
                if (not strict and ticker) or gate.can_commit(rec.review_id):
                    save_analysis(ticker=ticker, name=ticker, price=price,
                                  chg_pct=0.0, rsi=None, macd_signal="",
                                  summary=answer[:200], source="agent")
                self._last_review_id = rec.review_id
        except Exception as e:  # noqa: BLE001
            log.debug("长期记忆写入失败：%s", e)


def _is_mock_env() -> bool:
    import os
    return os.environ.get("STOCKAI_MOCK", "0") == "1"


def _review_mode() -> str:
    """human_review 审校模式：auto（默认自动写库+留记录）/ strict（审校后才写）。"""
    import os
    return os.environ.get("STOCKAI_REVIEW", "auto")
