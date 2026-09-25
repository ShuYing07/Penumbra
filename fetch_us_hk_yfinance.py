# -*- coding: utf-8 -*-
"""用yfinance拉美股+港股。"""
import json, time
import yfinance as yf

# 美股：yfinance没有全市场列表，但可以用已知的主要指数成分股
# 实际上用yfinance的download不行，需要ticker列表
# 用wikipedia或者known lists

print("=== 美股 ===")
# 用S&P 500 + NASDAQ 100 + DJIA 成分股作为基础
# yfinance有现成的方法
us_stocks = []

# S&P 500
try:
    sp500 = yf.Tickers(" ".join([
        "AAPL MSFT AMZN GOOGL META NVDA TSLA BRK-B JPM V MA UNH HD PG",
        "JNJ XOM CVX PFE MRK ABT ABBV KO PEP WMT COST TMO DHR LIN",
        "ORCL CRM ADBE NFLX AMD INTC QCOM TXN INTU AMAT LRCX KLAC",
        "MS NAX PEAK PARA DIS CMCSA T VZ TMUS BA CAT GE HON MMM",
        "UNP UPS FDX NKE SBUX MCD LOWS TJX ROST GM F HYC YUM",
        "SLB EOG XEC HAL BKR MPC VLO PSX COP OXY DVN",
        "CB SPGI AIG MET PRU AFL ALL TRV KKR APO",
    ]))
    for ticker in sp500.tickers:
        try:
            t = sp500.tickers[ticker]
            info = t.info
            name = info.get("shortName", ticker)
            us_stocks.append({
                "code": ticker, "name": name,
                "market": "美股", "board": "美股",
                "ticker": ticker, "secid_prefix": "105",
            })
        except:
            pass
    print(f"美股: {len(us_stocks)}")
except Exception as e:
    print(f"美股失败: {e}")

# 港股：用已知列表
print("=== 港股 ===")
hk_codes = [
    "00700", "09988", "03690", "02318", "00941", "01398", "00939", "03988",
    "02318", "01299", "00005", "00001", "00011", "00002", "00003", "00016",
    "00027", "00012", "00101", "00175", "00288", "00151", "00177", "00241",
    "00386", "00883", "01088", "01171", "00857", "00386", "01088", "01898",
    "00883", "00386", "00188", "01113", "00688", "00175", "00027", "00288",
]
hk_stocks = []
for code in hk_codes:
    try:
        t = yf.Ticker(f"{code}.HK")
        info = t.info
        name = info.get("shortName", code)
        hk_stocks.append({
            "code": code, "name": name,
            "market": "港股", "board": "港股主板",
            "ticker": code, "secid_prefix": "116",
        })
    except:
        pass
print(f"港股: {len(hk_stocks)}")

# 读A股
with open("data/a_stocks.json", encoding="utf-8") as f:
    a_stocks = json.load(f)

all_stocks = a_stocks + us_stocks + hk_stocks
seen = set()
uniq = []
for s in all_stocks:
    key = s["code"]
    if key not in seen:
        seen.add(key)
        uniq.append(s)

with open("data/all_stocks.json", "w", encoding="utf-8") as f:
    json.dump(uniq, f, ensure_ascii=False)

print(f"\n=== 总计 ===")
print(f"A股: {len(a_stocks)}")
print(f"美股: {len(us_stocks)}")
print(f"港股: {len(hk_stocks)}")
print(f"总计: {len(uniq)}")
