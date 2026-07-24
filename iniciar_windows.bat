@echo off
title YT-DLP GUI
cd /d "%~dp0"
python yt_dlp_gui.py
if errorlevel 1 pause
