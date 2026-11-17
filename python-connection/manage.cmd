@echo off
setlocal
py -3 -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0ai-connection.py" web
  goto done
)
python -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 (
  python "%~dp0ai-connection.py" web
  goto done
)
echo Python 3.11+ is required. Install Python or select it in CC Launcher.
pause
exit /b 1
:done
set connection_result=%errorlevel%
if not "%connection_result%"=="0" pause
exit /b %connection_result%
