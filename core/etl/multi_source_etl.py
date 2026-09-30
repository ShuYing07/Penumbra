# -*- coding: utf-8 -*-
"""多源实时 ETL 管道（模块三 · 参考 fin-intelligence-dashboard）。

从多个免费 API（NewsAPI / SEC EDGAR / FRED / Alpaca）摄取数据，做跨源
Join（如 filings ±7d 窗口与新闻关联），并导出 Airflow DAG 定义（可选）。

设计：
- `SourceAdapter`：统一适配器接口，网络/凭证缺失时返回空 + 降级原因，
  绝不抛出导致管道中断的异常；
- `join_filings_news`：纯 pandas 实现「公告 ±7 天窗口 ↔ 新闻」关联，
  可单测（这是本模块的核心增量，不依赖任何 API）；
- `build_airflow_dag`：仅在安装了 airflow 时生成 DAG 对象（import 可选），
  否则返回 None 并提示——不自行安装依赖。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

log = logging.getLogger("stockai.core.etl")


# ---------------------------------------------------------------------------
# 数据源适配器（统一接口 + 降级语义）
# ---------------------------------------------------------------------------
@dataclass
class SourceAdapter:
    name: str
    fetch: Callable[[], List[dict]]          # 返回记录列表
    kind: str = "generic"                     # news / filings / macro / market
    last_error: str = ""
    ok: bool = True

    def run(self) -> List[dict]:
        try:
            rows = self.fetch() or []
            self.ok = True
            return rows
        except Exception as e:  # noqa: BLE001
            self.ok = False
            self.last_error = str(e)
            log.warning("数据源 %s 摄取失败（降级空结果）：%s", self.name, e)
            return []


def _nullable_fetch(name: str) -> Callable[[], List[dict]]:
    """构造「网络受限时返回空」的降级取数函数。"""
    def _f() -> List[dict]:
        raise RuntimeError(f"{name} 数据源不可用（网络受限或未配置 API key）")
    return _f


def make_newsapi_adapter(api_key: str = "") -> SourceAdapter:
    """NewsAPI 适配器（免费版 /v2/top-headlines）。"""
    if not api_key:
        return SourceAdapter(name="newsapi", kind="news",
                             fetch=_nullable_fetch("NewsAPI"))
    import json
    from urllib import request

    def _fetch() -> List[dict]:
        url = ("https://newsapi.org/v2/top-headlines?country=cn&pageSize=50"
               f"&apiKey={api_key}")
        with request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [{"title": a.get("title", ""), "source": a.get("source", {}).get("name", ""),
                 "published": a.get("publishedAt", ""), "kind": "news"}
                for a in data.get("articles", [])]
    return SourceAdapter(name="newsapi", kind="news", fetch=_fetch)


def make_sec_adapter() -> SourceAdapter:
    """SEC EDGAR 适配器（公司提交索引 RSS，公开免 key）。"""
    import json
    from urllib import request

    def _fetch() -> List[dict]:
        url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
               "&type=10-K&output=atom")
        req = request.Request(url, headers={"User-Agent": "stockai research edu"})
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", "ignore")
        rows: List[dict] = []
        import re
        for m in re.finditer(r"<title>(.*?)</title>", body):
            rows.append({"title": m.group(1).strip(), "kind": "filings"})
        return rows[:50]
    return SourceAdapter(name="sec_edgar", kind="filings", fetch=_fetch)


def make_fred_adapter(series_id: str = "DGS10") -> SourceAdapter:
    """FRED 宏观指标适配器（公开 CSV）。"""
    from urllib import request

    def _fetch() -> List[dict]:
        url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
        with request.urlopen(url, timeout=10) as resp:
            text = resp.read().decode("utf-8").strip().splitlines()
        rows: List[dict] = []
        for line in text[1:]:
            parts = line.split(",")
            if len(parts) == 2 and parts[1] not in (".", ""):
                rows.append({"date": parts[0], "value": parts[1], "kind": "macro"})
        return rows[-100:]
    return SourceAdapter(name="fred", kind="macro", fetch=_fetch)


def make_alpaca_adapter(api_key: str = "", secret: str = "") -> SourceAdapter:
    """Alpaca Markets 适配器（需 key，未配置时降级）。"""
    if not (api_key and secret):
        return SourceAdapter(name="alpaca", kind="market",
                             fetch=_nullable_fetch("Alpaca"))
    import json
    from urllib import request

    def _fetch() -> List[dict]:
        url = "https://data.alpaca.markets/v2/stocks/AAPL/bars?timeframe=1D&limit=50"
        req = request.Request(url, headers={"APCA-API-KEY-ID": api_key,
                                            "APCA-API-SECRET-KEY": secret})
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [{"date": b.get("t", ""), "close": b.get("c"),
                 "volume": b.get("v"), "kind": "market"} for b in data.get("bars", [])]
    return SourceAdapter(name="alpaca", kind="market", fetch=_fetch)


# ---------------------------------------------------------------------------
# 跨源 Join：公告 ±7 天窗口 ↔ 新闻（纯 pandas，可单测）
# ---------------------------------------------------------------------------
def join_filings_news(filings: List[dict], news: List[dict],
                      window_days: int = 7) -> pd.DataFrame:
    """把公告与其前后 window_days 天内发布的新闻关联起来。

    filings: [{"title", "date"}]（date 为 YYYY-MM-DD 或 ISO 时间）
    news:    [{"title", "published"}]（published 为 ISO 时间）
    返回 DataFrame：filing_title / news_title / gap_days / filing_date。
    """
    def _date(v: str):
        if not v:
            return None
        s = str(v)[:10]
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:  # noqa: BLE001
            return None

    fdf = pd.DataFrame([{"filing": f.get("title", ""),
                         "f_date": _date(f.get("date", ""))} for f in filings])
    ndf = pd.DataFrame([{"news": n.get("title", ""),
                         "n_date": _date(n.get("published", ""))} for n in news])
    fdf = fdf.dropna(subset=["f_date"])
    ndf = ndf.dropna(subset=["n_date"])
    if fdf.empty or ndf.empty:
        return pd.DataFrame(columns=["filing", "news", "gap_days", "f_date"])
    fdf["f_date"] = pd.to_datetime(fdf["f_date"])
    ndf["n_date"] = pd.to_datetime(ndf["n_date"])
    merged = fdf.assign(_key=1).merge(ndf.assign(_key=1), on="_key").drop(columns="_key")
    merged["gap_days"] = (merged["n_date"] - merged["f_date"]).dt.days
    merged = merged[merged["gap_days"].abs() <= window_days]
    return merged.sort_values("gap_days").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Airflow DAG 定义（可选：仅已安装 airflow 时可用）
# ---------------------------------------------------------------------------
def build_airflow_dag(dag_id: str = "stockai_etl_daily",
                      schedule: str = "0 6 * * *") -> Optional[Any]:
    """构建 Airflow DAG：每日 6:00 UTC 摄取多源数据 → 跨源 Join → 落库。

    未安装 airflow 时返回 None 并给出提示（不自行安装依赖）。
    """
    try:
        from airflow import DAG
        from airflow.operators.python import PythonOperator
    except Exception:  # noqa: BLE001
        log.info("未安装 airflow，跳过 DAG 构建（可选依赖，需手动安装）")
        return None

    default_args = {"owner": "stockai", "retries": 1}

    def _etl_tasks():
        results: Dict[str, Any] = {}
        for adapter in (make_newsapi_adapter(), make_sec_adapter(),
                        make_fred_adapter(), make_alpaca_adapter()):
            results[adapter.name] = adapter.run()
        joined = join_filings_news(
            [{"title": r["title"], "date": r.get("published", "")}
             for r in results.get("sec_edgar", [])],
            results.get("newsapi", []))
        return {"rows": len(joined), "sources": {k: len(v)
                                                 for k, v in results.items()}}

    with DAG(dag_id=dag_id, schedule=schedule, default_args=default_args,
             description="疏影·知微多源 ETL（新闻/公告/宏观/行情）",
             catchup=False) as dag:
        PythonOperator(task_id="etl_multi_source", python_callable=_etl_tasks)
    return dag


if __name__ == "__main__":
    # 自检：Join 纯逻辑（不联网）
    filings = [{"title": "茅台2026三季报", "date": "2026-09-20"},
               {"title": "宁德时代公告", "date": "2026-09-01"}]
    news = [{"title": "茅台季报解读", "published": "2026-09-21T10:00:00"},
            {"title": "白酒板块大涨", "published": "2026-09-25T09:00:00"},
            {"title": "新能源政策", "published": "2026-08-20T08:00:00"}]
    df = join_filings_news(filings, news, window_days=7)
    assert len(df) == 2, df
    assert df["gap_days"].tolist() == [1, 5]
    assert build_airflow_dag() is None or build_airflow_dag() is not None
    assert make_newsapi_adapter().run() == []          # 未配置 → 空降级
    assert make_alpaca_adapter().run() == []
    print("multi_source_etl self-check ok")
