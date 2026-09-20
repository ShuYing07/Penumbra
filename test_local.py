# -*- coding: utf-8 -*-
"""测试本地AI连接"""
import sys, os
sys.path.insert(0, '.')

# 清除代理设置，避免localhost被代理转发
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(key, None)
os.environ['NO_PROXY'] = 'localhost,127.0.0.1'

from core.config import LOCAL_OLLAMA_URL, LOCAL_MODEL
print(f"Ollama URL: {LOCAL_OLLAMA_URL}")
print(f"默认模型: {LOCAL_MODEL}")

import requests
try:
    r = requests.get(f"{LOCAL_OLLAMA_URL}/api/tags", timeout=5)
    print(f"连接Ollama: {r.status_code}")
    data = r.json()
    models = [m['name'] for m in data.get('models', [])]
    print(f"已安装模型: {models}")
except Exception as e:
    print(f"连接失败: {e}")

# 测试实际推理
try:
    print("\n测试推理...")
    r = requests.post(f"{LOCAL_OLLAMA_URL}/api/generate", json={
        "model": LOCAL_MODEL,
        "prompt": "你好，请简单介绍一下你自己",
        "stream": False
    }, timeout=30)
    print(f"推理状态: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"回复: {data.get('response', '')[:200]}")
    else:
        print(f"错误: {r.text[:300]}")
except Exception as e:
    print(f"推理失败: {e}")
