@echo off
setlocal EnableExtensions
title RF4S Modding Toolkit
rem ---------------------------------------------------------------------------
rem  Double-click to start the RF4S modding GUI.
rem  First run: finds (or offers to install) 64-bit Python 3.10+, makes a private
rem  environment in .venv next to this file, installs requirements.txt into it.
rem  Later runs only check and start the GUI.
rem ---------------------------------------------------------------------------
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"

rem ---- already set up? --------------------------------------------------------
if exist "%VPY%" (
    "%VPY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>&1
    if not errorlevel 1 goto :deps
    echo The environment in .venv is broken, too old or 32-bit - rebuilding it.
    rmdir /s /q "%VENV%"
)

rem ---- find Python 3.10+ ------------------------------------------------------
call :findpy
if defined PY goto :mkvenv

echo.
echo 64-bit Python 3.10 or newer was not found on this PC (a 32-bit Python cannot
echo reach the 64-bit game, e.g. for Reload in game).
where winget >nul 2>&1
if errorlevel 1 goto :nopython
echo.
choice /c YN /m "Install Python 3.12 now with winget (Windows Package Manager)"
if errorlevel 2 goto :nopython
winget install -e --id Python.Python.3.12 --scope user
rem the new install is not on this window's PATH yet - look in the usual places
call :findpy
if defined PY goto :mkvenv
echo.
echo Python was installed, but this window cannot see it yet.
echo Close this window and double-click start.bat again.
goto :fail

:nopython
echo.
echo Please install 64-bit Python 3.10 or newer from https://www.python.org/downloads/
echo ("Windows installer (64-bit)"; tick "Add python.exe to PATH"), then run start.bat again.
start "" "https://www.python.org/downloads/"
goto :fail

rem ---- private environment ----------------------------------------------------
:mkvenv
echo Using %PY%
echo Creating the toolkit's Python environment in .venv ...
%PY% -m venv "%VENV%"
if errorlevel 1 (
    echo Could not create the environment. See the message above.
    goto :fail
)

rem ---- dependencies -----------------------------------------------------------
:deps
"%VPY%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo This Python has no Tkinter, which the GUI needs. Re-run the Python
    echo installer, choose Modify and tick "tcl/tk and IDLE".
    goto :fail
)
"%VPY%" -c "import PIL, texture2ddecoder, numpy" >nul 2>&1
if not errorlevel 1 goto :start
echo Installing the toolkit's libraries (Pillow, texture2ddecoder, numpy) ...
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%VPY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo Installing the libraries failed. Check your internet connection and the
    echo message above, then run start.bat again.
    goto :fail
)

rem ---- start the GUI (it asks for the game copy itself when none is found) -----
:start
echo Starting the RF4S modding GUI ... (keep this window open; closing it closes the GUI)
"%VPY%" "%~dp0rf4mod_gui.py" %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
pause
exit /b 1

rem ---- :findpy - sets PY to a 64-bit Python 3.10+ command, or leaves it empty -
:findpy
set "PY="
call :trypy "py" "-3-64"
call :trypy "py" "-3"
call :trypy "python" ""
call :trypy "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" "-3"
call :trypy "%SystemRoot%\py.exe" "-3"
call :trypy "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" ""
call :trypy "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" ""
exit /b 0

rem :trypy "exe" "args" - the Microsoft Store "python" alias and 32-bit Pythons fail this test
:trypy
if defined PY exit /b 0
"%~1" %~2 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 set PY="%~1" %~2
exit /b 0
