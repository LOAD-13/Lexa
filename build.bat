@echo off
title Lexa - Generar ejecutable
cd /d "%~dp0"
echo.
echo  ================================================
echo    Lexa - Generando Lexa.exe
echo  ================================================
echo.

REM El "python" del PATH no es necesariamente el que tiene las dependencias:
REM con varias versiones instaladas, compilar con el interprete equivocado
REM falla al instante con "PyInstaller no esta instalado". Se prueba cada uno
REM hasta dar con el que si puede importarlo.
set "PYEXE="
call :probe "python"
call :probe "py -3.13"
call :probe "py -3.12"
call :probe "py -3.11"
call :probe "py -3.10"

if not defined PYEXE (
  echo  No se encontro ningun Python con PyInstaller instalado.
  echo  Instalalo con:  pip install pyinstaller
  echo.
  pause
  exit /b 1
)

echo  Usando: %PYEXE%
echo.
%PYEXE% build_exe.py
echo.
pause
exit /b 0

:probe
REM Fija PYEXE con el primer interprete que logre importar PyInstaller.
if defined PYEXE exit /b 0
%~1 -c "import PyInstaller" >nul 2>&1
if not errorlevel 1 set "PYEXE=%~1"
exit /b 0
