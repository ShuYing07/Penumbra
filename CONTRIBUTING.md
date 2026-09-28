# 贡献指南（Contributing）

感谢你对 StockAIPredictor 的兴趣！欢迎提交 Issue 和 Pull Request。本项目定位为**本地化的金融数据分析与研究工具**，所有贡献都必须遵守"客观数据展示、不构成投资建议"的合规红线。

## 如何开始

1. Fork 本仓库到你的 GitHub 账号；
2. 克隆你 Fork 的副本：

```bash
git clone https://github.com/<your-username>/StockAIPredictor.git
cd StockAIPredictor
```

3. 新建特性分支：`git checkout -b feat/your-feature`。

## 开发环境

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
cp .env.example .env           # 填入你自己的 API Key
```

运行：`python -m app.main`

## 代码风格

- Python 3.11+，统一使用 **UTF-8** 编码；
- 遵循 PEP 8，行宽建议 100 字符；
- 公共函数/类需有简短 docstring；
- 不引入任何会**上传用户数据到第三方**的代码；
- **绝不硬编码任何 API Key**，所有密钥走 `.env`（已在 .gitignore）；
- 新功能必须保持"客观数据展示"定位，不得加入任何投资建议、买卖推荐逻辑。

## 提交 PR 标准流程

1. 确保本地测试全过：逐个运行 `tests/test_*.py`（全部 PASS）；
2. 按仓库内 `PULL_REQUEST_TEMPLATE.md` 填写勾选；
3. PR 标题清晰描述改动，必要时附上截图/复现步骤；
4. 通过 CI（密钥扫描、静态分析）并至少一名审查者通过。

## 新架构模块约定（Agent Mesh / 记忆 / 湖仓 / 适配器等）

- 新模块默认**标准库实现 + 可选依赖降级**（如 pyiceberg/pyspark/zmq 未装
  自动降级为内置实现并打印提示），不得因缺少可选依赖阻塞主程序；
- 每个新模块需带 `__main__` 自测（`python -m 包.模块`），并在
  `tests/test_enterprise_*.py` 中注册检查项；
- 数据获取必须保留多源降级链；线程/网络功能必须防重入；
- 合规类新能力（监控/规则/审计）必须记录原始输入与过滤结果，支持审计追溯。

## 合规红线（不可妥协）

任何 PR 不得：
- 提供具体证券的买卖建议、价格预测或个股推荐；
- 移除/弱化免责声明、隐私政策中的关键条款；
- 引入未经说明的网络上报/追踪。

期待你的贡献！
