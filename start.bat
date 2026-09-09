@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   AI Interview Assistant
echo ========================================
echo.

echo [1/2] 启动后端...
start "AI-Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo [2/2] 启动前端...
start "AI-Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo   后端:  http://localhost:8000/docs
echo   前端:  http://localhost:5173
echo.
echo   服务在另外两个窗口中运行，关闭它们即可停止服务。
echo ========================================

pause
