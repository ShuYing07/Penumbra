@echo off
chcp 65001 >nul
echo ========================================
echo    疏影·知微 启动测试脚本
echo ========================================
echo.

echo [1/5] 检查程序文件...
if not exist "dist\疏影知微\疏影知微.exe" (
    echo 错误: 找不到程序文件 dist\疏影知微\疏影知微.exe
    pause
    exit /b 1
)
echo ✓ 程序文件存在

echo [2/5] 检查依赖文件...
set missing_deps=0
for %%f in (
    "VCRUNTIME140.dll"
    "VCRUNTIME140_1.dll"
    "_asyncio.pyd"
    "_hashlib.pyd"
    "_ssl.pyd"
    "_sqlite3.pyd"
    "PyQt6\Qt6\bin\Qt6Core.dll"
    "PyQt6\Qt6\bin\Qt6Widgets.dll"
    "PyQt6\Qt6\bin\Qt6Gui.dll"
) do (
    if not exist "dist\疏影知微\%%f" (
        echo 警告: 缺少 %%f
        set missing_deps=1
    )
)
if %missing_deps%==0 (
    echo ✓ 所有依赖文件存在
) else (
    echo ⚠ 部分依赖文件缺失，程序可能无法正常运行
)

echo [3/5] 检查数据目录...
if not exist "dist\疏影知微\data" (
    echo 警告: data 目录不存在，将自动创建
    mkdir "dist\疏影知微\data" 2>nul
)
echo ✓ 数据目录准备就绪

echo [4/5] 检查配置文件...
if not exist "dist\疏影知微\.env" (
    echo 创建默认配置文件...
    echo DEEPSEEK_API_KEY=your_api_key_here > "dist\疏影知微\.env"
    echo # 请编辑此文件填入您的API密钥 >> "dist\疏影知微\.env"
)
echo ✓ 配置文件存在

echo [5/5] 运行程序...
echo.
echo ========================================
echo    即将启动疏影·知微
echo ========================================
echo.
echo 如果程序无法启动，请检查：
echo 1. 是否有足够的内存（建议8GB+）
echo 2. Windows Defender 是否阻止
echo 3. .NET Framework 4.8 是否安装
echo 4. Visual C++ Redistributable 2019 是否安装
echo.
pause

cd "dist\疏影知微"
start "" "疏影知微.exe"

echo 程序已启动，请等待主界面出现...
pause