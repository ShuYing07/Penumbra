# 快速上手

## Windows一键版
1. 下载 [疏影知微_v0.7.0.zip](https://github.com/ShuYing07/Penumbra/releases/latest)
2. 解压到任意目录
3. 双击 `疏影知微.exe`

## 源码版
```bash
git clone https://github.com/ShuYing07/Penumbra.git
cd Penumbra
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 编辑.env填入DEEPSEEK_API_KEY
python main.py
```

## 基本使用
1. 输入股票代码（如600519/AAPL/0700.HK）
2. 查看K线图和技术指标
3. 点击"多空辩论"查看AI分析
4. 自选股列表双击切换
