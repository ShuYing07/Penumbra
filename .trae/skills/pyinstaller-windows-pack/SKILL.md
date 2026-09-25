---
name: "pyinstaller-windows-pack"
description: "Packages Python desktop apps into Windows exe with PyInstaller onedir plus clean-dir selftest. Invoke when building exe or debugging frozen-env missing modules/DLLs."
---

# PyInstaller Windows 桌面程序打包（onedir + 冷库自检法）

把 Python 桌面 GUI（PyQt6 + pandas/numpy + akshare/chromadb/langgraph 等重栈）打包成
可在无 Python 环境的 Windows 上双击运行的 exe。核心方法论：**onedir 便携式 + collect_all
白名单 + `--selftest/--nettest` 冷库验收 + 证据导向排障**。源自 StockAIPredictor 项目
五期实测（Python 3.14 + PyInstaller 6.22，最终 338MB 一次验收 exit=0）。

## 何时使用

- 需要把 Python 桌面程序打包成 Windows exe / 换机器交付；
- 打包后的 exe 报缺模块、缺 DLL、缺数据文件（FileNotFoundError）；
- 打包版卡在网络/初始化但开发环境正常；
- 需要可重复的"构建→冷库冒烟→交付"流程。

## 标准流程（按序执行，不要跳步）

1. **冻结适配**（改入口与配置，见下节）。
2. **写 spec 与一键构建脚本**（onedir；console 调试版先行，windowed 终版最后）。
3. **构建控制台版**：长任务**单次启动、等它结束**，只看构建日志结尾的成功/失败，
   不要中途反复清理/重建。
4. **冷库验收**（关键）：清空/使用全新 `data/` 目录，在 dist 目录直接跑 exe：
   - `StockAIPredictor.exe --nettest` —— 逐源网络/依赖诊断，退出码 0 才算过；
   - `StockAIPredictor.exe --selftest` —— offscreen 构窗口 + mock 跑完整业务链路，
     结果写 `data/selftest.log`，**退出码 0 + 日志全 PASS** 才算过；
   - `StockAIPredictor.exe --localping` —— 若程序有本地模型后端（Ollama 等），
     冻结环境真实打一次本地推理，结果写 `data/localping.log`，验证回环代理绕过/模型调用链。
5. **windowed 终版**：spec 切 `console=False` 重建，复验 `--selftest` exit=0，
   再正常双击启动确认进程存活；最后清空验收产生的测试数据再交付。

## 一、冻结环境适配（代码侧，打包前必做）

```python
# core/config.py —— 数据目录放 exe 旁边（便携式，整目录可拷贝迁移）
import sys
from pathlib import Path
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
```

```python
# 日志：windowed 模式下 sys.stdout 为 None，StreamHandler 必须判空，只保留文件日志
if sys.stdout is not None:
    logger.addHandler(logging.StreamHandler(sys.stdout))
```

```python
# GUI 入口最前面：第三方爬虫库（akshare 等）部分请求无 timeout，冻结环境曾因此挂死
import socket
socket.setdefaulttimeout(30)
```

## 二、spec 要点（collect_all 白名单，实测清单）

```python
# packaging/app.spec  —— onedir；环境变量切 console/windowed
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

CONSOLE = os.environ.get("PACK_CONSOLE", "1") == "1"
datas, binaries, hidden = [], [], []

# 实测必须整体收集的包（datas+binaries+hiddenimports 缺一不可）：
for pkg in ("akshare", "py_mini_racer", "chromadb"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
datas += collect_data_files("pyqtgraph")

a = Analysis(["app/main.py"], pathex=["."], binaries=binaries, datas=datas,
             hiddenimports=hidden + [
                 "langchain_core.load", "langchain_core.serializable",  # LangGraph 动态 serde
             ],
             excludes=["tkinter", "IPython", "pytest", "torch", "tensorflow"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="App", console=CONSOLE)
coll = COLLECT(exe, a.binaries, a.datas, name="App")   # upx=False（中文路径易出问题）
```

**依赖缺失速查表（本项目实测，症状→根因→对策）：**

| 打包后症状 | 根因 | 对策 |
|---|---|---|
| 卡在"取数据/采集行情"，开发环境同路径秒回 | akshare 包内 `file_fold/*.json` 未收集（FileNotFoundError），**与网络无关** | `collect_all("akshare")` |
| 新浪快源静默失败、退化到 10s 备源 | `py_mini_racer/mini_racer.dll`（执行 JS）未收集 | `collect_all("py_mini_racer")` |
| `No module named 'chromadb.api.rust'` | chromadb ≥1.5 含 rust 绑定（.pyd） | `collect_all("chromadb")`（会带入 onnxruntime，约 +60MB） |
| 全新空库告警 `no such table`（dev 库不复现） | 查询先于建表的初始化顺序问题 | 管线入口先 `init_db()` + 决策表 init() |

规律：**凡带原生产物的小包（DLL/.pyd/rust 扩展）和包内数据文件（json/sql 迁移），
静态分析发现不了，一律想到 collect_all。**

## 三、内置两个自检模式（交付给用户也能排障）

```python
# app/main.py：--selftest 冷库全链路（QT offscreen + mock，不依赖真实 API key/余额）
def _selftest() -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("STOCKAI_MOCK", "1")
    # 构主窗口 → 触发一次完整业务流程 → 用 processEvents 泵事件循环等待后台 QThread
    # 注意：后台线程结果必须轮询等待（给足超时，如 120s），不能立即断言
    # 每行结果 append 到列表，最后写 data/selftest.log；全 PASS 返回 0，异常返回 1

# --nettest 逐源诊断：requests.get(各数据源, timeout=15) + 调真实取数函数，
# 打印每源耗时/状态码，写 data/nettest.log。冻结环境问题先用它定位，不要猜。
```

要点：windowed 模式没有控制台，自检结果**必须落文件 + 用退出码判定**，不能只 print。

## 四、验收命令（Windows PowerShell）

```powershell
# windowed（GUI 子系统）进程脱离控制台，$LASTEXITCODE 拿不到，必须 Start-Process：
$p = Start-Process -FilePath .\dist\App\App.exe -ArgumentList '--selftest' -Wait -PassThru -NoNewWindow
$p.ExitCode          # 必须为 0
Get-Content .\dist\App\data\selftest.log -Encoding UTF8

# 正常启动存活验证：启动后等 10~15 秒，进程未退出即 GUI 正常
$p = Start-Process -FilePath .\dist\App\App.exe -PassThru
Start-Sleep 12; if (!$p.HasExited) { "OK PID=$($p.Id)"; Stop-Process -Id $p.Id -Force }
```

## 纪律红线

- **onedir，不用 onefile**（onefile 每次解压临时目录、启动慢、易被杀软误报）。
- **冷库（空 data/、无 Python）冒烟是强制验收项**——dev 热库会掩盖建表顺序、缺数据文件等问题。
- **证据导向**：冻结版与开发版行为不一致时，先加逐源自检拿日志，不猜网络/代理；
  本项目首轮误判"网络挂了"，真因是缺 json 文件。
- 长构建单次启动等完成，输出重定向到日志文件（`*> pack_log.txt`）防超时丢输出。
- 交付目录带：exe、`.env`（含本机 key 时**仅限本人，分发他人前删除**）、使用说明、空 data/。
- 体积参考：空 PyQt6 约 90MB；+akshare 数据约 234MB；+mini_racer 约 272MB；
  +chromadb/onnxruntime 约 338MB。想瘦身先验证 import 链再 excludes（自研嵌入不依赖 onnxruntime）。
- Python 3.14 无需降级：PyInstaller ≥6.22 已支持（6.20+ 修复了 3.14 forkserver 问题）。
