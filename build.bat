@echo off
title Lexa - Generar ejecutable
cd /d "%~dp0"
echo.
echo  ================================================
echo    Lexa - Generando Lexa.exe
echo  ================================================
echo.
python build_exe.py
echo.
pause
