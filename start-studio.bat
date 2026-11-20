@echo off
setlocal EnableDelayedExpansion
title RocqiPath Studio
chcp 65001 >nul 2>&1
cd /d "%~dp0"

:: Double-click to start RocqiPath Studio on http://127.0.0.1:8765.
:: The first run creates .venv and installs RocqiPath (5-10 minutes).
:: Delete the .venv folder to force a clean reinstall.
:: Extra arguments go to `rocqipath studio`, e.g. --workspace D:\StudioWork.
:: To use another port, change PORT below.

:: Optional: your python.exe, quotes included, e.g.
::   set "PYTHON_PATH="C:\Program Files\Python311\python.exe""
:: Leave empty to use the Python launcher (py) with 3.11 or 3.10.
set "PYTHON_PATH="
set "PORT=8765"
set "MARKER=.venv\.studio_ready"

echo.
echo   RocqiPath Studio
echo   --------------------------------------------------------------
echo.

:: -- 1. Find Python ----------------------------------------------------
echo   [1/3]  Locating Python...
if exist "%MARKER%" goto :ready
if not defined PYTHON_PATH (
    for %%V in (3.11 3.10) do (
        if not defined PYTHON_PATH (
            py -%%V -c "import sys" >nul 2>&1 && set "PYTHON_PATH=py -%%V"
        )
    )
)
if not defined PYTHON_PATH (
    echo   [X]  Python 3.10 or 3.11 was not found.
    echo        Install it from https://www.python.org/downloads/windows/
    echo        or set PYTHON_PATH at the top of this file.
    pause & exit /b 1
)
for /f "tokens=*" %%V in ('!PYTHON_PATH! --version 2^>^&1') do echo   [OK] %%V

:: -- 2. Create the environment (first run only) -------------------------
echo   [2/3]  Setting up the environment...
if not exist ".venv\Scripts\python.exe" (
    !PYTHON_PATH! -m venv .venv
    if errorlevel 1 (
        echo   [X]  Could not create the virtual environment.
        pause & exit /b 1
    )
)
echo          Installing packages, this can take 5-10 minutes...
.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
:: openslide-bin and pyvips[binary] bundle the native libraries Windows lacks.
.venv\Scripts\python.exe -m pip install --quiet -e ".[studio,extraction,orb,stain,cellcount,viz]" openslide-bin "pyvips[binary]"
if errorlevel 1 (
    echo   [X]  Package installation failed. Check your internet connection.
    pause & exit /b 1
)
echo ready> "%MARKER%"
goto :launch

:ready
echo   [OK] Environment already set up
echo   [2/3]  Skipping installation

:: -- 3. Launch -----------------------------------------------------------
:launch
echo   [3/3]  Starting Studio...
echo.
echo   --------------------------------------------------------------
echo   http://127.0.0.1:%PORT%
echo   Keep this window open while you work. Press Ctrl+C to stop.
echo   --------------------------------------------------------------
echo.
:: Open the browser a few seconds later, once the server is listening.
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start "" http://127.0.0.1:%PORT%"
.venv\Scripts\rocqipath.exe studio --port %PORT% %*
echo.
echo   Studio stopped. Press any key to close.
pause >nul
