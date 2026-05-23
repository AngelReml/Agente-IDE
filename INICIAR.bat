@echo off
chcp 65001 >nul
title Swarm IDE

echo.
echo  ==========================================
echo   SWARM IDE
echo  ==========================================
echo.

REM ?? Comprobar que INSTALAR.bat se haya ejecutado ???????????????????????????????
if not exist "%~dp0backend\venv\Scripts\activate.bat" (
    echo  [ERROR] Entorno Python no encontrado.
    echo          Ejecuta primero INSTALAR.bat
    echo.
    pause
    exit /b 1
)
if not exist "%~dp0frontend\node_modules" (
    echo  [ERROR] Dependencias frontend no encontradas.
    echo          Ejecuta primero INSTALAR.bat
    echo.
    pause
    exit /b 1
)

REM ?? Comprobar si los puertos ya estan en uso ??????????????????????????????????
netstat -aon 2>nul | findstr /R ":8000 .*LISTENING" >nul
if %errorlevel% equ 0 (
    echo  [AVISO] El puerto 8000 ya esta en uso.
    echo          Puede que el backend ya este corriendo.
    echo          Si quieres reiniciarlo, ejecuta primero PARAR.bat
    echo.
)

netstat -aon 2>nul | findstr /R ":3000 .*LISTENING" >nul
if %errorlevel% equ 0 (
    echo  [AVISO] El puerto 3000 ya esta en uso.
    echo          Puede que el frontend ya este corriendo.
    echo.
)

REM ?? Arrancar backend en ventana separada ??????????????????????????????????????
echo  Iniciando backend...
start "Swarm IDE - Backend" cmd /k "%~dp0_run_backend.bat"

REM Dar tiempo al backend para arrancar antes del frontend
timeout /t 4 /nobreak >nul

REM ?? Arrancar frontend en ventana separada ?????????????????????????????????????
echo  Iniciando frontend...
start "Swarm IDE - Frontend" cmd /k "%~dp0_run_frontend.bat"

REM Dar tiempo a Next.js para compilar (primera vez puede tardar 10-15s)
echo  Esperando a que el frontend compile...
timeout /t 20 /nobreak >nul

REM ?? Abrir el navegador ????????????????????????????????????????????????????????
echo  Abriendo navegador...
start "" "http://localhost:3000"

echo.
echo  ==========================================
echo   Swarm IDE corriendo en:
echo   http://localhost:3000
echo.
echo   Para PARAR: ejecuta PARAR.bat
echo   o cierra las dos ventanas negras.
echo  ==========================================
echo.
timeout /t 5 /nobreak >nul
