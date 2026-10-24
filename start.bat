@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   AI Interview Assistant - one-click start
echo ========================================
echo.

REM ---------- 0. preflight ----------
where docker >nul 2>nul
if errorlevel 1 goto no_docker

docker info >nul 2>nul
if errorlevel 1 goto docker_down

if not exist "backend\requirements.txt" goto wrong_dir
if not exist "backend\.env" goto no_env

set "COMPOSE=docker compose"
docker compose version >nul 2>nul
if errorlevel 1 set "COMPOSE=docker-compose"
%COMPOSE% version >nul 2>nul
if errorlevel 1 goto no_compose

where npm >nul 2>nul
if errorlevel 1 goto no_node

set "PY="
if exist "%~dp0backend\.venv\Scripts\python.exe" call :try_python "%~dp0backend\.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0venv\Scripts\python.exe" call :try_python "%~dp0venv\Scripts\python.exe"
if not defined PY call :try_python "python"
if not defined PY goto no_python

call :port_busy 8000
if not errorlevel 1 goto port_8000
call :port_busy 5173
if not errorlevel 1 goto port_5173

REM ---------- 1. Redis ----------
echo [1/4] starting Redis ...
%COMPOSE% up -d
if errorlevel 1 goto redis_start_fail

set /a redis_tries=0
:wait_redis
docker exec ai-interview-redis redis-cli ping >nul 2>nul
if not errorlevel 1 goto redis_ready
set /a redis_tries+=1
if %redis_tries% geq 30 goto redis_timeout
ping -n 2 127.0.0.1 >nul
goto wait_redis
:redis_ready
echo         Redis ready

REM ---------- 2. backend ----------
echo [2/4] starting backend ...
start "AI-Backend" cmd /k "cd /d "%~dp0backend" && "%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
echo         waiting for http://127.0.0.1:8000/health ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=(Get-Date).AddSeconds(60); while((Get-Date) -lt $d){ try { if((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:8000/health').StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 goto backend_timeout

REM ---------- 3. frontend ----------
echo [3/4] starting frontend ...
start "AI-Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev -- --host 127.0.0.1"
echo         waiting for http://127.0.0.1:5173 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=(Get-Date).AddSeconds(60); while((Get-Date) -lt $d){ try { if((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:5173').StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 goto frontend_timeout

REM ---------- 4. browser ----------
echo [4/4] opening browser
start "" "http://127.0.0.1:5173"

echo.
echo ========================================
echo   all ready
echo ----------------------------------------
echo   frontend  http://127.0.0.1:5173
echo   backend   http://127.0.0.1:8000/docs
echo   health    http://127.0.0.1:8000/health
echo ========================================
echo.
echo Services run in the AI-Backend / AI-Frontend windows.
echo Close those windows to stop them. Redis keeps running (docker compose stop).
exit /b 0


REM ---------- helpers ----------
:try_python
"%~1" -c "import uvicorn, fastapi" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0

:port_busy
netstat -ano | findstr /c:":%1 " | findstr /c:"LISTENING" >nul
exit /b %errorlevel%


REM ---------- errors ----------
:no_docker
echo [error] docker not found.
echo         Install Docker Desktop and make sure its bin directory is on PATH.
goto fail

:docker_down
echo [error] Docker is installed but not running.
echo         Start Docker Desktop first, then run this script again.
goto fail

:wrong_dir
echo [error] This does not look like the repository root (backend\requirements.txt missing).
echo         Put start.bat in the repository root and run it there.
goto fail

:no_env
echo [error] backend\.env is missing.
echo         Run:  copy backend\.env.example backend\.env
echo         Then fill in the LLM and Embedding API keys.
goto fail

:no_compose
echo [error] docker compose / docker-compose not found.
echo         Upgrade Docker Desktop to a version that ships Compose V2.
goto fail

:no_node
echo [error] npm not found, cannot start the frontend.
echo         Install Node 18+ and make sure npm is on PATH.
goto fail

:no_python
echo [error] No usable Python found (needs uvicorn + fastapi).
echo         In the backend directory run:
echo             python -m venv .venv
echo             .venv\Scripts\activate
echo             pip install -r requirements.txt
goto fail

:redis_start_fail
echo [error] Redis failed to start. Check the docker compose output above.
goto fail

:redis_timeout
echo [error] Redis was not ready within 30 seconds.
echo         Check logs: docker logs ai-interview-redis
goto fail

:port_8000
echo [error] Port 8000 is already in use, backend cannot start.
echo         Find it:  netstat -ano ^| findstr :8000
echo         Kill it:  taskkill /PID ^<PID^> /F
goto fail

:port_5173
echo [error] Port 5173 is already in use, frontend cannot start.
echo         Find it:  netstat -ano ^| findstr :5173
echo         Kill it:  taskkill /PID ^<PID^> /F
goto fail

:backend_timeout
echo [error] Backend did not pass the health check within 60 seconds.
echo         See the error in the AI-Backend window.
goto fail

:frontend_timeout
echo [error] Frontend did not become ready within 60 seconds.
echo         See the error in the AI-Frontend window.
goto fail

:fail
echo.
pause
exit /b 1
