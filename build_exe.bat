@echo off
REM 一键打包脚本（在项目根目录、已激活 venv 的终端中双击/运行）
REM 产物在 dist\ShuyingInsight\
call venv\Scripts\activate.bat
pyinstaller --onedir --noconsole --name ShuyingInsight main.py
pause
