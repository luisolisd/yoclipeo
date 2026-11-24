@echo off
title YoClipeo
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto install
echo Iniciando YoClipeo en http://127.0.0.1:8765 ...
echo (Cierra esta ventana para apagarlo.)
".venv\Scripts\python.exe" app.py
pause
exit /b

:install
echo Primero abre "Instalar YoClipeo.bat".
pause
