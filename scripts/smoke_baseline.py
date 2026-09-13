# -*- coding: utf-8 -*-
"""一期基线连通性测试：akshare(A股) / yfinance(美股+加密) / DeepSeek。
用法：venv\\Scripts\\python.exe scripts\\smoke_baseline.py
"""
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 载入 .env
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def test_akshare():
    import akshare as ak
    print("\n[1] akshare 取 A股 600519(贵州茅台) 最近日线 ...")
    t0 = time.time()
    df = ak.stock_zh_a_hist(symbol="600519", period="daily", adjust="qfq")
    print(f"    行数={len(df)}  耗时={time.time()-t0:.1f}s")
    print("    列名:", list(df.columns))
    print(df.tail(3).to_string(max_cols=8))
    return True


def test_yfinance(ticker, proxy=None):
    import yfinance as yf
    tag = f"{ticker}" + (f" via proxy {proxy}" if proxy else " 直连")
    print(f"\n[2] yfinance 取 {tag} ...")
    t0 = time.time()
    old_http = os.environ.get("HTTP_PROXY")
    old_https = os.environ.get("HTTPS_PROXY")
    try:
        if proxy:
            os.environ["HTTP_PROXY"] = proxy
            os.environ["HTTPS_PROXY"] = proxy
        else:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
        df = yf.download(ticker, period="1mo", interval="1d", progress=False, auto_adjust=True)
        print(f"    行数={len(df)}  耗时={time.time()-t0:.1f}s")
        if len(df):
            print(df.tail(3).to_string(max_cols=6))
        return len(df) > 0
    finally:
        if old_http is not None:
            os.environ["HTTP_PROXY"] = old_http
        if old_https is not None:
            os.environ["HTTPS_PROXY"] = old_https


def test_deepseek():
    from openai import OpenAI
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    print(f"\n[3] DeepSeek ping (key 长度={len(key)}) ...")
    if not key:
        print("    跳过：未配置 DEEPSEEK_API_KEY")
        return False
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=30)
    t0 = time.time()
    r = client.chat.completions.create(
        model="deepseek-flash",
        messages=[{"role": "user", "content": "只回复两个字：正常"}],
        max_tokens=20,
        temperature=0.1,
    )
    msg = r.choices[0].message.content
    print(f"    回复={msg!r}  耗时={time.time()-t0:.1f}s  tokens={r.usage.total_tokens}")
    return True


if __name__ == "__main__":
    results = {}
    for name, fn in [
        ("akshare", lambda: test_akshare()),
        ("yf_AAPL_direct", lambda: test_yfinance("AAPL")),
        ("yf_AAPL_proxy", lambda: test_yfinance("AAPL", "http://127.0.0.1:7897")),
        ("yf_BTC_proxy", lambda: test_yfinance("BTC-USD", "http://127.0.0.1:7897")),
        ("deepseek", test_deepseek),
    ]:
        try:
            results[name] = "OK" if fn() else "EMPTY"
        except Exception as e:
            results[name] = f"FAIL: {type(e).__name__}: {e}"
            traceback.print_exc()
    print("\n===== 基线汇总 =====")
    for k, v in results.items():
        print(f"  {k:18s} {v}")
