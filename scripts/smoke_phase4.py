# -*- coding: utf-8 -*-
"""四期冒烟：RAG 学习库（入库/检索）+ 相似形态检索 + mock 管线注入 + 学习库 UI。

运行：venv\\Scripts\\python.exe scripts\\smoke_phase4.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["STOCKAI_MOCK"] = "1"

from core.data import service  # noqa: E402
from core.llm import LLMRunner  # noqa: E402
from core.memory import rag  # noqa: E402
from core.memory.patterns import find_similar  # noqa: E402


def wait_until(pred, timeout_s: float, app) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    print("== 1. RAG：哈希嵌入 + 入库 + 检索 ==")
    rag.add_docs([
        {"text": "止损纪律：单笔亏损不超过总资金2%，跌破关键支撑立即离场，绝不心存侥幸。",
         "kind": "resource", "ticker": "", "date": "2026-09-10", "title": "止损纪律", "ref": "t1"},
        {"text": "美联储降息预期升温，成长股估值压力缓解，科技板块走强。",
         "kind": "news", "ticker": "AAPL", "date": "2026-09-10", "title": "降息预期", "ref": "t2"},
        {"text": "贵州茅台高端白酒动销平稳，渠道库存健康，估值处于历史低位。",
         "kind": "news", "ticker": "SH600519", "date": "2026-09-10", "title": "白酒动销", "ref": "t3"},
    ])
    hits = rag.search("跌破支撑位怎么办 止损")
    assert hits, "检索无结果"
    assert hits[0]["meta"]["kind"] == "resource" and hits[0]["score"] > 0.3, \
        f"排序异常: {[(h['meta']['kind'], h['score']) for h in hits]}"
    n_rep = rag.index_reports()
    st = rag.stats()
    assert st["total"] >= 4 and st["by_kind"].get("report", 0) >= 1, f"报告入库异常 {st}"
    print(f"PASS RAG：语义检索命中[{hits[0]['meta']['kind']}{hits[0]['score']}]，"
          f"报告入库{n_rep}条，库内 {st['total']} 条 {st['by_kind']}")

    print("== 2. 相似历史形态检索 ==")
    bars, _ = service.get_daily("SH600519")
    matches, agg = find_similar(bars)
    assert len(matches) == 5 and agg, f"形态匹配异常: {len(matches)}"
    m0 = matches[0]
    assert 0 < m0["similarity_pct"] <= 100 and isinstance(m0["forward_ret_pct"], float), \
        f"匹配字段异常 {m0}"
    # 无前视检查：匹配窗口必须早于当前窗口
    assert m0["end_date"] < bars.index[-1].strftime("%Y-%m-%d"), "匹配窗口与当前重叠"
    print(f"PASS 形态：TOP1 {m0['start_date']}~{m0['end_date']} 相似{m0['similarity_pct']}% "
          f"后10日{m0['forward_ret_pct']:+.2f}%；均值{agg['avg_forward_ret_pct']:+.2f}% "
          f"上涨占比{agg['up_ratio_pct']}%")

    print("== 3. mock 管线注入 ==")
    from core.agents.graph import run_analysis
    from core.report import render
    result = run_analysis("SH600519", runner=LLMRunner(mock=True))
    state = result["state"]
    assert state.get("patterns"), "state.patterns 未注入"
    md = render(state)
    assert "历史相似形态检索" in md, "报告缺相似形态节"
    hits2 = rag.search(f"{state['ticker']} 分析结论")
    assert any(h["meta"]["kind"] == "report" for h in hits2), "当次分析结论未自动入库"
    print(f"PASS 注入：patterns {len(state['patterns'])} 段入报告；"
          f"结论自动入库（检索到 '{hits2[0]['meta']['title']}'）")

    print("== 4. 学习库 UI ==")
    from PyQt6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication([])
    win = MainWindow()
    win.show()
    win.knowledge_tab.query.setText("白酒 渠道 库存")
    win.knowledge_tab._do_search()
    ok = wait_until(lambda: win.knowledge_tab.rag_table.rowCount() > 0, 60, app)
    assert ok, "语义检索 UI 无结果"
    win.knowledge_tab.ticker.setText("SH600519")
    win.knowledge_tab._do_pattern()
    ok = wait_until(lambda: win.knowledge_tab.pat_table.rowCount() > 0, 120, app)
    assert ok, "形态检索 UI 无结果"
    print(f"PASS UI：检索{win.knowledge_tab.rag_table.rowCount()}条；"
          f"形态{win.knowledge_tab.pat_table.rowCount()}段；{win.knowledge_tab.lbl_stats.text()}")
    print("\n四期冒烟全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
