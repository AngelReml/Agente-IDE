@echo off
title Swarm IDE - Backend
cd /d "%~dp0backend"
call venv\Scripts\activate
echo Backend iniciado en http://localhost:8000
echo.
REM Por defecto enlaza a loopback (solo este PC). Para exponer en la LAN define
REM SWARM_HOST=0.0.0.0 y SWARM_AUTH_TOKEN=<token> en el .env (auth obligatoria).
if "%SWARM_HOST%"=="" set SWARM_HOST=127.0.0.1
if "%SWARM_PORT%"=="" set SWARM_PORT=8000
uvicorn app.main:app --host %SWARM_HOST% --port %SWARM_PORT%
