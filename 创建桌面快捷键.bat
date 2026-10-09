@echo off
chcp 65001 >nul
title 疏影·知微 - 桌面快捷键创建工具

echo ==========================================================
echo         疏影·知微 AI金融数据分析终端 - 桌面快捷键创建工具
echo ==========================================================
echo.

echo 正在检查系统环境...
echo.

:: 检查可执行文件是否存在
if not exist "dist\疏影知微\疏影知微.exe" (
    echo [错误] 找不到可执行文件：dist\疏影知微\疏影知微.exe
    echo.
    echo 请确保已正确打包应用程序。运行以下命令进行打包：
    echo   pyinstaller 疏影知微.spec --clean
    echo.
    pause
    exit /b 1
)

echo [✓] 可执行文件检查通过
echo [✓] 打包目录：dist\疏影知微\
echo [✓] 主程序：疏影知微.exe
echo.

echo 正在创建桌面快捷键...
echo.

:: 创建VBScript文件用于创建快捷键
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%temp%\create_shortcut.vbs"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\疏影·知微.lnk" >> "%temp%\create_shortcut.vbs"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%temp%\create_shortcut.vbs"
echo oLink.TargetPath = "%CD%\dist\疏影知微\疏影知微.exe" >> "%temp%\create_shortcut.vbs"
echo oLink.WorkingDirectory = "%CD%\dist\疏影知微" >> "%temp%\create_shortcut.vbs"
echo oLink.Description = "疏影·知微 AI金融数据分析终端" >> "%temp%\create_shortcut.vbs"
echo oLink.IconLocation = "%CD%\dist\疏影知微\疏影知微.exe, 0" >> "%temp%\create_shortcut.vbs"
echo oLink.WindowStyle = 1 >> "%temp%\create_shortcut.vbs"
echo oLink.Save >> "%temp%\create_shortcut.vbs"

:: 执行VBScript创建快捷键
cscript "%temp%\create_shortcut.vbs" >nul

:: 清理临时文件
if exist "%temp%\create_shortcut.vbs" del "%temp%\create_shortcut.vbs"

:: 检查快捷键是否创建成功
if exist "%USERPROFILE%\Desktop\疏影·知微.lnk" (
    echo [✓] 桌面快捷键创建成功！
    echo.
    echo 快捷键位置：%USERPROFILE%\Desktop\疏影·知微.lnk
    echo.
    echo 您现在可以通过以下方式启动程序：
    echo   1. 双击桌面上的"疏影·知微"图标
    echo   2. 或直接运行 dist\疏影知微\疏影知微.exe
    echo.
) else (
    echo [警告] 快捷键创建可能失败，请手动创建：
    echo.
    echo 手动创建步骤：
    echo 1. 右键点击桌面，选择"新建" -> "快捷方式"
    echo 2. 在位置栏输入：%CD%\dist\疏影知微\疏影知微.exe
    echo 3. 点击"下一步"，输入名称"疏影·知微"
    echo 4. 点击"完成"
    echo.
)

echo ==========================================================
echo 快捷键创建工具完成
echo ==========================================================
echo.
pause