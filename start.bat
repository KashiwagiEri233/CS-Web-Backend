@echo off
REM 优雅启动FastAPI RBAC框架 - Windows批处理脚本

echo.
echo ====================================
echo   FastAPI RBAC Framework 启动器
echo ====================================
echo.

REM 检查虚拟环境是否存在
if exist ".venv\Scripts\activate.bat" (
    echo 激活虚拟环境...
    call .venv\Scripts\activate.bat
) else (
    echo 警告: 未找到虚拟环境，使用系统Python
)

REM 检查是否安装了依赖
python -c "import fastapi" 2>nul
if errorlevel 1 (
    echo 正在安装依赖...
    pip install -r requirements.txt
)

echo.
echo 启动FastAPI应用...
echo.
python startup.py

pause