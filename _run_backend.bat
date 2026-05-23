@echo off
title Swarm IDE - Backend
cd /d "%~dp0backend"
call venv\Scripts\activate
echo Backend iniciado en http://localhost:8000
echo.
uvicorn app.main:app --host 0.0.0.0 --port 8000
