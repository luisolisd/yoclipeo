@echo off
setlocal
title Instalar YoClipeo
cd /d "%~dp0"
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=py -3.11"
)
if defined PY goto have
where python >nul 2>nul
if errorlevel 1 goto nopython
python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else 1)" >nul 2>nul
if errorlevel 1 goto nopython
set "PY=python"

:have
if exist ".venv\Scripts\python.exe" goto deps
echo [1/3] Preparando la carpeta .venv ...
%PY% -m venv .venv
if errorlevel 1 goto failed

:deps
echo [2/3] Instalando lo necesario. La primera vez baja unos 200 MB ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed

where nvidia-smi >nul 2>nul
if errorlevel 1 goto check
if /i "%~1"=="/singpu" goto check
echo.
echo Este equipo tiene una GPU NVIDIA. Sus librerias aceleran la voz, pero pesan
echo cerca de 2 GB y tienen licencia propia de NVIDIA. Se pueden agregar despues.
choice /c SN /m "Instalarlas ahora"
if errorlevel 2 goto check
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-nvidia.txt
if errorlevel 1 echo No se pudieron instalar. La voz usara el procesador.

:check
echo [3/3] Comprobando ...
".venv\Scripts\python.exe" -c "import anthropic, av, cv2, ctranslate2, fastapi, faster_whisper, multipart, numpy, onnxruntime, PIL, uvicorn, yt_dlp; from cliper import config, vision; vision._faces_model(); import os; assert os.path.exists(config.FFMPEG), 'falta ffmpeg'"
if errorlevel 1 goto badcheck
echo.
echo Listo. Abre "Iniciar YoClipeo.bat".
echo Para elegir clips con IA en tu PC instala Ollama (https://ollama.com).
echo El modelo de voz se baja solo con el primer video.
goto end

:nopython
echo.
echo Falta Python 3.11 de 64 bits. Bajalo de https://www.python.org/downloads/release/python-3119/
echo marca "Add python.exe to PATH" al instalarlo y vuelve a abrir este archivo.
goto bad

:badcheck
echo.
echo Se instalo, pero algo no carga. Si arriba dice que falta una DLL, instala
echo "Microsoft Visual C++ Redistributable" (x64) y vuelve a abrir este archivo.
goto bad

:failed
echo.
echo No se pudo instalar. Revisa tu internet y el espacio en disco, y vuelve a
echo abrir este archivo: sigue donde se quedo.

:bad
pause
exit /b 1

:end
pause
exit /b 0
