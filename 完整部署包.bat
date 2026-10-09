@echo off
chcp 65001 >nul
echo ========================================
echo    疏影·知微 完整部署包生成
echo ========================================
echo.

echo [1/5] 清理旧文件...
if exist "dist\疏影知微" rmdir /s /q "dist\疏影知微"
if exist "build\疏影知微" rmdir /s /q "build\疏影知微"
echo ✓ 清理完成

echo [2/5] 安装必要依赖...
echo 正在安装 PyQt6...
python -m pip install PyQt6 --user
echo 正在安装 pandas...
python -m pip install pandas --user
echo 正在安装 akshare...
python -m pip install akshare --user
echo 正在安装 langgraph...
python -m pip install langgraph --user
echo ✓ 依赖安装完成

echo [3/5] 重新打包...
python -m PyInstaller 疏影知微.spec --clean --noconfirm
if errorlevel 1 (
    echo 错误: 打包失败
    pause
    exit /b 1
)
echo ✓ 打包完成

echo [4/5] 验证文件...
if not exist "dist\疏影知微\疏影知微.exe" (
    echo 错误: 程序文件不存在
    pause
    exit /b 1
)
echo ✓ 程序文件存在

echo [5/5] 创建启动器...
echo @echo off > "dist\疏影知微\启动.bat"
echo chcp 65001 ^>nul >> "dist\疏影知微\启动.bat"
echo echo 正在启动疏影·知微... >> "dist\疏影知微\启动.bat"
echo echo 如果程序无法启动，请确保： >> "dist\疏影知微\启动.bat"
echo echo 1. 已安装 .NET Framework 4.8 >> "dist\疏影知微\启动.bat"
echo echo 2. 已安装 Visual C++ Redistributable 2019 >> "dist\疏影知微\启动.bat"
echo echo 3. 防火墙允许程序运行 >> "dist\疏影知微\启动.bat"
echo echo. >> "dist\疏影知微\启动.bat"
echo start "" "疏影知微.exe" >> "dist\疏影知微\启动.bat"
echo ✓ 启动器创建完成

echo.
echo ========================================
echo    部署包已准备就绪
echo ========================================
echo.
echo 程序位置: dist\疏影知微\
echo 启动方式: 双击 "启动.bat" 或 "疏影知微.exe"
echo.
echo 桌面快捷方式创建方法:
echo 1. 打开 dist\疏影知微 文件夹
echo 2. 右键拖拽 疏影知微.exe 到桌面
echo 3. 选择"创建快捷方式"
echo.
pause