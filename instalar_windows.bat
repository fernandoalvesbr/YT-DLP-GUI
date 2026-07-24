@echo off
title Instalador - YT-DLP GUI
cd /d "%~dp0"
python -m pip install -U pip
python -m pip install -U -r requirements.txt
echo.
echo Instalacao concluida.
echo Para abrir, execute iniciar_windows.bat
pause
