@echo off
rem Start the report viewer server (double-click). Opens the browser automatically. Closing this window stops the server.
rem NOTE: keep this file ASCII-only. cmd.exe reads batch files in the OEM code page and breaks on UTF-8 text.
rem Python 3 lookup order: py launcher -> python3 -> python (must actually run; the Microsoft Store stub is skipped)
rem                        -> %LOCALAPPDATA%\Programs\Python -> %ProgramFiles%\Python3x -> C:\Python3x
setlocal
cd /d "%~dp0"
set "PYEXE="
set "PYARGS="
py -3 -c "import sys" >nul 2>nul && (set "PYEXE=py" & set "PYARGS=-3")
if not defined PYEXE python3 -c "import sys" >nul 2>nul && set "PYEXE=python3"
if not defined PYEXE python -c "import sys" >nul 2>nul && set "PYEXE=python"
if not defined PYEXE for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (set "PYEXE=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" & set "PYARGS=-3")
if not defined PYEXE for /d %%D in ("%ProgramFiles%\Python3*" "C:\Python3*") do if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
if not defined PYEXE (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)
"%PYEXE%" %PYARGS% "_viewer\serve.py" %*
if errorlevel 1 (
  echo.
  echo The server exited with an error. See the messages above.
  pause
)
