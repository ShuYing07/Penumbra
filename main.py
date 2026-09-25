# -*- coding: utf-8 -*-
"""疏影·知微 桌面程序根目录入口。

运行：python main.py
打包：见 build_exe.bat
说明：实际实现位于 app/main.py，此文件仅为方便从根目录直接启动。
"""
from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
