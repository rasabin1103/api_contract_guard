@echo off
setlocal
title ASE API Contract Guard
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start.ps1" %*
set "_ACG_EXIT_CODE=%ERRORLEVEL%"
if not "%_ACG_EXIT_CODE%"=="0" (
  echo.
  echo No se ha podido iniciar el servicio. Revisa el mensaje anterior.
  pause
)
exit /b %_ACG_EXIT_CODE%
