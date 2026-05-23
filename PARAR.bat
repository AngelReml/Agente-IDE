@echo off
chcp 65001 >nul
title Swarm IDE - Parar

echo.
echo  Parando Swarm IDE...
echo.

REM ?? Matar proceso en puerto 8000 (backend) ?????????????????????????????????????
set KILLED_BACKEND=0
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /R ":8000 .*LISTENING"') do (
    if not "%%a"=="0" (
        taskkill /f /pid %%a >nul 2>&1
        set KILLED_BACKEND=1
    )
)
if %KILLED_BACKEND%==1 (
    echo  [OK] Backend parado.
) else (
    echo  [--] Backend no estaba corriendo.
)

REM ?? Matar proceso en puerto 3000 (frontend) ????????????????????????????????????
set KILLED_FRONTEND=0
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /R ":3000 .*LISTENING"') do (
    if not "%%a"=="0" (
        taskkill /f /pid %%a >nul 2>&1
        set KILLED_FRONTEND=1
    )
)
if %KILLED_FRONTEND%==1 (
    echo  [OK] Frontend parado.
) else (
    echo  [--] Frontend no estaba corriendo.
)

echo.
echo  Swarm IDE parado.
echo.
timeout /t 2 /nobreak >nul
