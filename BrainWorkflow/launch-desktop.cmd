@echo off
setlocal DisableDelayedExpansion
"%__APPDIR__%cscript.exe" //nologo "%~dp0launch-desktop.vbs" %*
exit /b %errorlevel%
