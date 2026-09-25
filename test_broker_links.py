# -*- coding: utf-8 -*-
"""测试券商链接和安全跳转。"""
from broker_links import list_brokers, get_broker_link
from safe_url_opener import safe_open_url

print("=== 1. 券商列表 ===")
brokers = list_brokers()
print(f"共{len(brokers)}家: {brokers}")

print("\n=== 2. URL校验 ===")
for name in brokers:
    info = get_broker_link(name)
    url = info["url"]
    assert url.startswith("https://"), f"{name} 不是https: {url}"
    assert "10jqka" not in url and "dazhihui" not in url, f"{name} 指向第三方"
    print(f"  OK {name}: {url}")

print("\n=== 3. 安全跳转 ===")
assert not safe_open_url("javascript:alert(1)"), "应拒绝javascript"
assert not safe_open_url("-ls"), "应拒绝-开头"
assert not safe_open_url("ftp://test.com"), "应拒绝非http"
print("  恶意URL全部被拦截")

print("\n全部测试通过")
