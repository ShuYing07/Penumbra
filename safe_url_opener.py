# -*- coding: utf-8 -*-
"""安全打开URL：强制校验，防止命令注入。"""
from __future__ import annotations

import webbrowser
from urllib.parse import urlparse


def safe_open_url(url: str) -> bool:
    """安全打开URL，校验格式后调用系统默认浏览器。"""
    # 1. 必须是http/https
    if not url.startswith(("http://", "https://")):
        print(f"[安全警告] 拒绝非http(s) URL: {url[:50]}")
        return False

    # 2. 不能以-开头（防止命令注入）
    parsed = urlparse(url)
    if not parsed.netloc or parsed.netloc.startswith("-"):
        print(f"[安全警告] 无效域名: {url[:50]}")
        return False

    # 3. 用系统默认浏览器新标签页打开
    try:
        webbrowser.open(url, new=2)
        return True
    except Exception as e:
        print(f"[错误] 打开URL失败: {e}")
        return False


if __name__ == "__main__":
    # 测试
    print(safe_open_url("https://www.htsc.com.cn/"))  # OK
    print(safe_open_url("javascript:alert(1)"))        # 拒绝
    print(safe_open_url("-ls"))                         # 拒绝
