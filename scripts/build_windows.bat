@echo off
REM ============================================================
REM  One-shot Windows build script (ASCII only, CRLF endings).
REM  Robust version: never relies on pip/activate on PATH.
REM  Network is needed for the BUILD only; the built app is
REM  fully offline.
REM
REM  Prerequisite: Python 3.12 from python.org
REM ============================================================

cd /d "%~dp0\.."

REM ---- locate a real Python (py launcher first, then python) ----
set "PYTHON="

py -3.12 --version >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3.12"

if not defined PYTHON (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON=py -3"
)

if not defined PYTHON (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    echo [ERROR] No working Python found.
    echo Install Python 3.12 from https://www.python.org/downloads/
    echo IMPORTANT: check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

echo Using Python: %PYTHON%
%PYTHON% --version

echo.
echo === 1/4 Creating virtual environment ===
if not exist .venv-build\Scripts\python.exe (
    %PYTHON% -m venv .venv-build
)
if not exist .venv-build\Scripts\python.exe (
    echo [ERROR] Failed to create the virtual environment.
    echo Your "python" may be the Microsoft Store stub.
    echo Install Python 3.12 from python.org and retry.
    pause
    exit /b 1
)

set "VPY=.venv-build\Scripts\python.exe"

echo.
echo === 2/4 Installing dependencies ===
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt pyinstaller huggingface-hub --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if errorlevel 1 goto error

echo.
echo === 3/4 Checking models (skipped if already present) ===
if not exist model\model.bin (
    "%VPY%" scripts\download_model.py .
    if errorlevel 1 goto error
)
if not exist llm\qwen2.5-3b-instruct-q4_k_m.gguf (
    "%VPY%" scripts\download_model.py .
    if errorlevel 1 goto error
)

echo.
echo === 4/4 Building with PyInstaller ===
"%VPY%" -m PyInstaller app.spec --noconfirm
if errorlevel 1 goto error

echo.
echo === Copying models and dictionary into the output folder ===
xcopy /e /i /y model "dist\OfflineTranscriber\model" >nul
xcopy /e /i /y llm "dist\OfflineTranscriber\llm" >nul
copy /y dictionary.json "dist\OfflineTranscriber\" >nul

echo.
echo ============================================================
echo  DONE! Output: dist\OfflineTranscriber\
echo  Copy that whole folder to the target PC and run
echo  OfflineTranscriber.exe - no network needed at runtime.
echo ============================================================
pause
exit /b 0

:error
echo.
echo [ERROR] Build failed. Please report the messages above.
pause
exit /b 1
