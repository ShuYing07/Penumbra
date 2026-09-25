# -*- coding: utf-8 -*-
"""测试新闻管道"""
import sys
sys.path.insert(0, '.')
from core.data.news_pipeline import fetch_stock_news, fetch_announcements, fetch_hot_news

print("=== 个股新闻 ===")
try:
    news = fetch_stock_news('SH600519', limit=5)
    for n in news[:5]:
        print(f"  [{n.get('sentiment','?')}] {n.get('title','')[:60]} ({n.get('publish_time','')[:10]})")
except Exception as e:
    print(f"  FAIL: {e}")

print("\n=== 公司公告 ===")
try:
    anns = fetch_announcements('SH600519', limit=5)
    for a in anns[:5]:
        print(f"  {a.get('title','')[:60]} ({a.get('publish_time','')[:10]})")
except Exception as e:
    print(f"  FAIL: {e}")

print("\n=== 热点新闻 ===")
try:
    hot = fetch_hot_news(limit=5)
    for n in hot[:5]:
        print(f"  {n.get('title','')[:60]} ({n.get('source','')})")
except Exception as e:
    print(f"  FAIL: {e}")
