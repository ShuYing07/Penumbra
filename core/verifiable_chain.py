# -*- coding: utf-8 -*-
"""可验证思维链（模块一 · 参考 FinChain / FORCE-Bench）。

让 AI 分析输出可验证的推理步骤：每一步 = 结论 + 数据来源 + 计算公式。
本模块提供：
- `VERIFIABLE_CHAIN_SYSTEM`：注入 System Prompt 的格式约束；
- `extract_verifiable_steps(text)`：从报告文本解析「步骤」块，
  产出 [{step, conclusion, source, formula}]（解析器不依赖 LLM，可单测）；
- `chain_markdown(steps)`：把步骤流渲染成 UI 可读的推理链 Markdown；
- `validate_chain(steps)`：校验每步是否具备 conclusion/source/formula 三要素。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# System Prompt 追加段：要求可验证推理链
VERIFIABLE_CHAIN_SYSTEM = (
    "输出要求：所有关键结论必须给出【可验证推理链】。\n"
    "每个关键结论按如下格式输出（每步一行）：\n"
    "步骤N｜结论：<结论>｜数据来源：<原始数据或获取时间>｜公式：<计算式>\n"
    "例如：步骤1｜结论：RSI=62.9 中性偏强｜数据来源：近30日收盘价（获取于 2026-09-30）｜公式：RSI(14)=100-100/(1+平均涨幅/平均跌幅)\n"
    "数据来源缺失的结论视为不可验证，宁可省略结论也不要编造来源。"
)

_STEP_RE = re.compile(
    r"步骤\s*(\d+)\s*[｜|]\s*结论[:：]\s*(.*?)\s*[｜|]\s*数据来源[:：]\s*(.*?)\s*[｜|]\s*公式[:：]\s*(.*?)(?:\n|$)",
    re.S)


def extract_verifiable_steps(text: str) -> List[Dict[str, str]]:
    """从报告文本中解析可验证推理链步骤。失败或缺失字段的步骤被跳过。"""
    steps: List[Dict[str, str]] = []
    for m in _STEP_RE.finditer(text or ""):
        step = {"step": m.group(1).strip(),
                "conclusion": m.group(2).strip(),
                "source": m.group(3).strip(),
                "formula": m.group(4).strip()}
        if step["conclusion"] and step["source"] and step["formula"]:
            steps.append(step)
    return steps


def validate_chain(steps: List[Dict[str, str]]) -> Dict[str, object]:
    """校验推理链完整性：返回通过数 / 总数 / 缺失清单。"""
    ok, missing = 0, []
    for s in steps or []:
        lacks = [k for k in ("conclusion", "source", "formula")
                 if not (s.get(k) or "").strip()]
        if lacks:
            missing.append({"step": s.get("step"), "missing": lacks})
        else:
            ok += 1
    return {"passed": ok, "total": len(steps or []),
            "missing": missing,
            "verdict": "PASS" if missing == [] and len(steps or []) > 0
                       else ("EMPTY" if not steps else "PARTIAL")}


def chain_markdown(steps: List[Dict[str, str]]) -> str:
    """把步骤渲染成推理链 Markdown（供 UI 推理链查看面板）。"""
    if not steps:
        return "（无推理链）"
    lines = ["### 🔗 可验证推理链"]
    for s in steps:
        lines.append(f"- **步骤{s.get('step')}**：{s.get('conclusion')}")
        lines.append(f"  - 数据来源：{s.get('source')}")
        lines.append(f"  - 公式：`{s.get('formula')}`")
    return "\n".join(lines)


if __name__ == "__main__":
    text = ("步骤1｜结论：RSI=62.9 中性偏强｜数据来源：近30日收盘价｜"
            "公式：RSI(14)=100-100/(1+平均涨幅/平均跌幅)\n"
            "步骤2｜结论：MACD 金叉｜数据来源：日线 close｜公式：MACD=DIF-DEA\n"
            "步骤3｜结论：缺来源结论｜公式：x")
    steps = extract_verifiable_steps(text)
    assert len(steps) == 2, steps
    r = validate_chain(steps)
    assert r["passed"] == 2 and r["verdict"] == "PASS"
    md = chain_markdown(steps)
    assert "可验证推理链" in md and "RSI=62.9" in md
    assert validate_chain([])["verdict"] == "EMPTY"
    print("verifiable_chain self-check ok")
