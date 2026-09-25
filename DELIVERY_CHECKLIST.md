# 交付前检查清单（每次发布必过，不许跳）

> 这是从反复失败里总结的硬规则。做完一步没验证，等于没做。

## push / 发布后
1. **必须等 CI 跑完再宣布成功**：push 后用
   `GET /repos/{owner}/{repo}/actions/runs?per_page=1`
   看最新 run 的 `conclusion == success`。红色就修，不许装没看见。
2. **合规词表会扫 *.md**：写文档举例时，不要把词表里的收益承诺类敏感词原样写进 .md（CI 的 grep 会命中）。需要举例时统一写"预设敏感词表"即可，完整词表见 `.github/workflows/compliance_check.yml`。

## 上传 Release 资产
3. **浏览器 UI 传大文件不可靠**：点 "1 file selected" ≠ 传完。
   当前网络（~23KB/s）下 397MB 会卡死或被丢弃。
4. **改用 API 上传**：取 git 凭据 `git credential fill`，走本地代理 `127.0.0.1:7897`，
   POST 到 `uploads.github.com/.../assets?name=...`，timeout 至少 900s。
5. **必须硬验证 asset**：上传后 `GET /releases/tags/<tag>`，确认
   有对应 asset、`state == "uploaded"`、size 与本地 zip 一致（±5MB），
   并打印 `browser_download_url`。assets 为空就等于没传。

## 代码/打包
6. PyInstaller 产物名以 spec 为准（本项目是 `疏影知微.exe`），
   不要靠打包脚本硬编码的旧名判断成败；跑完必须 `--selftest` 看日志。
7. 严禁终端 echo/Remove-Item 改代码文件；统一用编辑器工具，UTF-8。
