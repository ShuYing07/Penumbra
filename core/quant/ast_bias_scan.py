# -*- coding: utf-8 -*-
"""回测代码静态审计（AST）——在策略**执行前**拦截前视偏差。

为什么必须有 AST 静态检查：
运行时的"截断重算法"（用截止 D 的数据重算一遍特征，对比是否变化）很可靠，
但它要求先把策略跑起来、且只对"能跑通"的代码有效。AST 静态检查在
**代码执行之前**就能指出问题，两者互补：

- 静态：快、无需数据、能定位到 文件:行，适合做 CI 门禁与上线前拦截；
- 动态：能发现"逻辑上偷看了未来"但语法上很干净的实现。

参考 SolidRockQuant / backtest-audit 的红旗清单，结合 A 股回测常见坑，
本模块实现 9 条规则，输出统一为
**缺陷 × 证据 × 严重度 × 影响 × 修复** 五元组。

严重度：FATAL（回测结果不可用，必须改）/ WARN（需人工确认）/ INFO（提示）。
"""
from __future__ import annotations

import ast
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("stockai.quant.astscan")

Severity = str  # "FATAL" | "WARN" | "INFO"


@dataclass
class Finding:
    """一条审计发现：缺陷 × 证据 × 严重度 × 影响 × 修复。"""
    rule_id: str
    defect: str
    evidence: str                      # 文件:行:列 + 代码片段
    severity: Severity
    impact: str
    fix: str
    line: int = 0
    col: int = 0
    snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"rule_id": self.rule_id, "defect": self.defect,
                "evidence": self.evidence, "severity": self.severity,
                "impact": self.impact, "fix": self.fix,
                "line": self.line, "col": self.col, "snippet": self.snippet}


@dataclass
class ScanReport:
    target: str = ""
    findings: List[Finding] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and not any(f.severity == "FATAL" for f in self.findings)

    @property
    def blocking(self) -> bool:
        """是否应阻止进入回测（存在 FATAL）。"""
        return bool(self.error) or any(f.severity == "FATAL" for f in self.findings)

    def by_severity(self, sev: Severity) -> List[Finding]:
        return [f for f in self.findings if f.severity == sev]

    def to_dict(self) -> Dict[str, Any]:
        return {"target": self.target, "passed": self.passed,
                "blocking": self.blocking,
                "counts": {"FATAL": len(self.by_severity("FATAL")),
                           "WARN": len(self.by_severity("WARN")),
                           "INFO": len(self.by_severity("INFO"))},
                "findings": [f.to_dict() for f in self.findings],
                "error": self.error}


# ---------------------------------------------------------------------------
# 规则实现
# ---------------------------------------------------------------------------
def _seg(src_lines: List[str], node: ast.AST, width: int = 3) -> str:
    """取出节点附近的代码片段作为证据。"""
    lo = max(1, getattr(node, "lineno", 1) - 1)
    hi = min(len(src_lines), getattr(node, "end_lineno", lo) + width - 1)
    return " / ".join(l.strip() for l in src_lines[lo - 1:hi] if l.strip())[:200]


_WINDOW_FUNCS = ("rolling", "expanding", "ewm", "groupby", "resample", "cumsum",
                 "cummax", "cummin", "cumprod")


def _is_windowed(node: ast.Call) -> bool:
    """判断聚合是否发生在窗口/分组上下文里（rolling(20).mean() 是合法的历史统计）。

    没有这一层判断，A04 会把所有滚动均线都误报成"全样本归一化"——
    误报比漏报更伤：它会让人养成无视告警的习惯。
    """
    cur: Any = node.func
    depth = 0
    while cur is not None and depth < 8:
        if isinstance(cur, ast.Attribute):
            if cur.attr in _WINDOW_FUNCS:
                return True
            cur = cur.value                 # 继续向左：rolling(20).mean() → rolling
        elif isinstance(cur, ast.Call):
            cur = cur.func                  # 穿过调用层：Call(rolling) → Attribute(rolling)
        elif isinstance(cur, ast.Subscript):
            cur = cur.value                 # 穿过下标层：groupby(k)["c"].mean()
        else:
            break
        depth += 1
    return False


def _neg_shift_value(node: ast.Call) -> Optional[int]:
    """识别 shift(-N) / pct_change(-N) / diff(-N) 中的负数参数。"""
    for a in node.args:
        if isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub):
            if isinstance(a.operand, ast.Constant) and isinstance(a.operand.value, (int, float)):
                return -int(a.operand.value)
        if isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) and a.value < 0:
            return int(a.value)
    return None


_FUTURE_WORDS = ("future", "fwd", "next_", "next_ret", "label", "target", "forward")


def scan_source(source: str, filename: str = "<strategy>") -> ScanReport:
    """对策略源码做 AST 静态审计。"""
    report = ScanReport(target=filename)
    if not source or not source.strip():
        report.error = "源码为空"
        return report
    try:
        try:
            tree = ast.parse(source)
        except IndentationError:
            # 类体内/函数内定义的策略函数，取到的源码带缩进 → 先 dedent 再解析
            import textwrap
            tree = ast.parse(textwrap.dedent(source))
    except SyntaxError as e:
        report.error = f"语法错误，无法解析：{e}"
        return report

    src_lines = source.splitlines()
    findings: List[Finding] = []

    def add(rule_id, defect, node, severity, impact, fix):
        snippet = _seg(src_lines, node)
        findings.append(Finding(
            rule_id=rule_id, defect=defect,
            evidence=f"{filename}:{getattr(node, 'lineno', 0)}:{getattr(node, 'col_offset', 0)} → {snippet}",
            severity=severity, impact=impact, fix=fix,
            line=getattr(node, "lineno", 0), col=getattr(node, "col_offset", 0),
            snippet=snippet))

    for node in ast.walk(tree):
        # A01 / A07：shift(-n) / pct_change(-n) / diff(-n) —— 明目张胆地取未来值
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            m = node.func.attr
            if m in ("shift", "pct_change", "diff", "rolling_shift"):
                n = _neg_shift_value(node)
                if n is not None and n < 0:
                    add("A01", f"{m}({n}) 使用了未来数据（负位移把后面的值搬到当前行）",
                        node, "FATAL",
                        "信号在 t 时刻读到 t+1..t+n 的数据，回测收益被系统性高估，实盘必然失效",
                        f"改为 {m}({abs(n)}) 取历史值；或先 .shift(1) 再用于当日决策")

            # A02：bfill / backfill —— 用后面的值回填前面
            if m in ("bfill", "backfill"):
                add("A02", f"{m}() 用后续观测回填缺失值", node, "FATAL",
                    "缺失值被未来数据填补，等价于前视偏差",
                    "改用 ffill()（只回看历史）或明确填充常量/插值后截断")
            if m == "fillna":
                for kw in node.keywords:
                    if kw.arg == "method" and isinstance(kw.value, ast.Constant) \
                            and str(kw.value.value) in ("bfill", "backfill"):
                        add("A02", "fillna(method='bfill') 用未来值回填", node, "FATAL",
                            "缺失值被未来数据填补，等价于前视偏差",
                            "改用 method='ffill'，或先填充再 shift(1)")

            # A03：rolling(center=True) —— 窗口居中，右半边是未来
            if m == "rolling":
                for kw in node.keywords:
                    if kw.arg == "center" and isinstance(kw.value, ast.Constant) \
                            and kw.value.value is True:
                        add("A03", "rolling(center=True) 窗口包含未来数据", node, "FATAL",
                            "指标值使用了窗口右半侧（未来）的数据",
                            "去掉 center=True；如需平滑，用 rolling(n).mean().shift(1)")

            # A04：全样本归一化（mean/max/min/std 作用于**整列**，而非滚动窗口）
            if (m in ("mean", "max", "min", "std", "quantile")
                    and not node.args and not node.keywords
                    and not _is_windowed(node)):
                add("A04", f".{m}() 对整列做聚合（疑似全样本归一化）", node, "WARN",
                    "若用于标准化/归一化，则引入了整段样本的统计量（未来信息）",
                    "改用滚动窗口：rolling(n).mean() 或 expanding() 并 shift(1)")

        # A05：循环里用 iloc[i + n] 前视索引
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.BinOp):
            ops = (ast.Add,)
            if isinstance(node.slice.op, ops):
                right = node.slice.right
                if isinstance(right, ast.Constant) and isinstance(right.value, int) and right.value > 0:
                    add("A05", f"iloc/下标 使用了 i+{right.value} 的前向索引", node, "WARN",
                        "循环内读取了当前位置之后的 bar",
                        "确认取的是「下一根 bar 的成交价」（合法撮合）"
                        "还是「下一根 bar 的信号」（违规前视）")

        # A06：未来语义命名（future/next_/target/label…）
        if isinstance(node, ast.Name) and any(w in node.id.lower() for w in _FUTURE_WORDS):
            add("A06", f"存在未来语义标识符 {node.id}", node, "INFO",
                "命名含 future/next/target/label 的变量常用于监督学习标签，"
                "若被当作特征使用即构成标签泄漏",
                "确认该变量只作为预测目标（y），不得进入特征矩阵 X")
        if isinstance(node, ast.Attribute) and any(w in node.attr.lower() for w in _FUTURE_WORDS):
            add("A06", f"存在未来语义字段 {node.attr}", node, "INFO",
                "同上，可能是标签列被误当特征",
                "特征工程阶段显式剔除标签列")
        # 列名常量的未来语义：df["fwd_ret"] / df["future_close"]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            if any(w in low for w in _FUTURE_WORDS):
                add("A06", f"存在未来语义列名 {node.value!r}", node, "INFO",
                    "该列名含 future/fwd/next/target/label，通常是监督学习的预测目标；"
                    "若被当作特征使用即构成标签泄漏",
                    "确认该列只作为 y（预测目标），在构造 X 时显式剔除")

    # 去重（同一行同一规则只保留一条）
    seen = set()
    uniq: List[Finding] = []
    for f in findings:
        key = (f.rule_id, f.line)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    uniq.sort(key=lambda f: ({"FATAL": 0, "WARN": 1, "INFO": 2}[f.severity], f.line))
    report.findings = uniq
    return report


def scan_function(fn: Callable[..., Any]) -> ScanReport:
    """审计一个策略函数（用 inspect 取源码）。"""
    try:
        src = inspect.getsource(fn)
    except Exception as e:  # noqa: BLE001
        r = ScanReport(target=getattr(fn, "__name__", "<fn>"))
        r.error = f"无法获取源码：{e}"
        return r
    return scan_source(src, filename=f"{getattr(fn, '__module__', '')}.{getattr(fn, '__name__', '')}")


def scan_file(path: str) -> ScanReport:
    """审计一个策略源码文件。"""
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except Exception as e:  # noqa: BLE001
        r = ScanReport(target=path)
        r.error = f"读取失败：{e}"
        return r
    return scan_source(src, filename=path)


def preflight(strategy: Any = None, source: str = "", path: str = "") -> Dict[str, Any]:
    """回测前置门禁：任一入口命中 FATAL 即返回 blocking=True（调用方应拦截）。"""
    if path:
        rep = scan_file(path)
    elif source:
        rep = scan_source(source)
    elif callable(strategy):
        rep = scan_function(strategy)
    else:
        rep = ScanReport(target=str(strategy)[:40])
        rep.error = "未提供可审计对象（需要 path / source / callable 之一）"
    return rep.to_dict()


def format_report(rep: ScanReport) -> str:
    """人读格式：缺陷 × 证据 × 严重度 × 影响 × 修复。"""
    d = rep.to_dict()
    if d["error"]:
        return f"审计无法进行：{d['error']}"
    if not rep.findings:
        return f"✅ {rep.target} 静态审计通过，未发现前视偏差红旗"
    lines = [f"静态审计报告 · {rep.target} · "
             f"致命 {d['counts']['FATAL']} / 警告 {d['counts']['WARN']} / 提示 {d['counts']['INFO']}"]
    for f in rep.findings:
        lines.append(f"\n[{f.severity}] {f.rule_id} {f.defect}")
        lines.append(f"  证据：{f.evidence}")
        lines.append(f"  影响：{f.impact}")
        lines.append(f"  修复：{f.fix}")
    if rep.blocking:
        lines.append("\n⛔ 存在致命项，建议修复后再回测（回测门禁将拦截）")
    return "\n".join(lines)
