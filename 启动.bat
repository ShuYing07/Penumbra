@echo off
chcp 65001 >nul
title 疏影·知微 - AI金融数据分析终端

echo ========================================
echo    疏影·知微 正在启动...
echo ========================================
echo.

echo [1/3] 检查运行环境...
if not exist "疏影知微.exe" (
    echo 错误: 找不到程序文件！
    echo 请确保在 dist\疏影知微\ 目录下运行此脚本
    pause
    exit /b 1
)
echo ✓ 程序文件存在

if not exist "_internal" (
    echo 错误: 缺少依赖库！
    echo 请重新运行打包脚本
    pause
    exit /b 1
)
echo ✓ 依赖库完整

echo [2/3] 检查配置文件...
if not exist ".env" (
    echo 创建默认配置文件...
    echo DEEPSEEK_API_KEY=your_api_key_here > .env
    echo # 请编辑此文件填入您的API密钥 >> .env
    echo ✓ 配置文件已创建
) else (
    echo ✓ 配置文件存在
)

echo [3/3] 创建数据目录...
if not exist "data" mkdir data
if not exist "data\logs" mkdir data\logs
echo ✓ 数据目录准备就绪

echo.
echo ========================================
echo    启动程序...
echo ========================================
echo.
echo 如果程序无法启动，请检查：
echo 1. 是否有足够的内存（建议8GB+）
echo 2. Windows Defender 是否阻止
echo 3. .NET Framework 4.8 是否安装
echo 4. Visual C++ Redistributable 2019 是否安装
echo.
echo 正在启动疏影·知微...
echo.

start "" "疏影知微.exe"

echo 程序已启动，请等待主界面出现...
echo.
echo 如果需要查看日志，请检查 data\logs\ 目录
echo.
pause