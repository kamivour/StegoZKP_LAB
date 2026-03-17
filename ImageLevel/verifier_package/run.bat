@echo off
setlocal enabledelayedexpansion

REM =============================================================================
REM  ZK-SNARK DICOM Steganography -- Single-Command Verifier Entry Point (Windows)
REM =============================================================================
REM  Usage:
REM    run.bat                          auto-detects stego image in sent_image\
REM    run.bat path\to\stego.png        specify image explicitly
REM    run.bat path\to\stego.png -v     verbose output
REM    run.bat path\to\stego.png --json JSON output
REM
REM  This script:
REM    1. Checks and installs all dependencies (Python, Node.js, snarkjs, packages)
REM    2. Auto-detects the stego image if none is provided
REM    3. Runs ZK proof verification (+ metadata extraction if chaos_key.txt present)
REM =============================================================================

set SCRIPT_DIR=%~dp0
if "!SCRIPT_DIR:~-1!"=="\" set SCRIPT_DIR=!SCRIPT_DIR:~0,-1!

REM Capture first arg as image path; remaining args passed through to verify.py
set IMAGE_ARG=%~1
set EXTRA_ARGS=
if not "%~2"=="" (
    REM Collect all args after the first
    set _SKIP=1
    for %%A in (%*) do (
        if !_SKIP! EQU 1 (
            set _SKIP=0
        ) else (
            set EXTRA_ARGS=!EXTRA_ARGS! %%A
        )
    )
)

REM =============================================================================
REM  PHASE 1 -- Dependency setup
REM =============================================================================
echo.
echo ============================================================
echo   Phase 1: Dependency check
echo ============================================================

call "!SCRIPT_DIR!\setup.bat"
if !ERRORLEVEL! NEQ 0 (
    echo.
    echo ERROR: Setup phase failed. Fix the issues above and re-run run.bat.
    pause
    exit /b 1
)

REM =============================================================================
REM  PHASE 2 -- Locate stego image
REM =============================================================================
echo.
echo ============================================================
echo   Phase 2: Locating stego image
echo ============================================================

set IMAGE=

if not "!IMAGE_ARG!"=="" (
    REM Explicit path provided
    if exist "!IMAGE_ARG!" (
        set IMAGE=!IMAGE_ARG!
    ) else if exist "!SCRIPT_DIR!\!IMAGE_ARG!" (
        set IMAGE=!SCRIPT_DIR!\!IMAGE_ARG!
    ) else (
        echo ERROR: Image not found: !IMAGE_ARG!
        pause
        exit /b 1
    )
    echo Using specified image: !IMAGE!
) else (
    REM Auto-detect: first PNG in sent_image\
    set SENT_DIR=!SCRIPT_DIR!\sent_image
    if exist "!SENT_DIR!\" (
        for %%F in ("!SENT_DIR!\*.png") do (
            if "!IMAGE!"=="" set IMAGE=%%F
        )
    )
    if "!IMAGE!"=="" (
        echo No stego image found.
        echo Either:
        echo   - Place a stego PNG in:  !SCRIPT_DIR!\sent_image\
        echo   - Or run:                run.bat path\to\stego.png
        pause
        exit /b 1
    )
    echo Auto-detected: !IMAGE!
)

REM =============================================================================
REM  PHASE 3 -- Verify (and extract if chaos_key.txt present)
REM =============================================================================
echo.
echo ============================================================
echo   Phase 3: ZK verification + extraction
echo ============================================================

REM Find Python (fast path -- already installed by setup.bat)
set PYTHON_CMD=
for %%P in (python3 python py) do (
    if "!PYTHON_CMD!"=="" (
        where %%P >nul 2>nul
        if !ERRORLEVEL! EQU 0 (
            for /f "tokens=2" %%V in ('%%P --version 2^>^&1') do (
                for /f "tokens=1,2 delims=." %%A in ("%%V") do (
                    if %%A GEQ 3 if %%B GEQ 9 set PYTHON_CMD=%%P
                )
            )
        )
    )
)

if "!PYTHON_CMD!"=="" (
    echo ERROR: Python 3.9+ not found even after setup.
    echo Re-open this terminal (to refresh PATH) and run run.bat again.
    pause
    exit /b 1
)

set VERIFY_SCRIPT=!SCRIPT_DIR!\scripts\verify.py
if not exist "!VERIFY_SCRIPT!" (
    echo ERROR: verify.py not found at: !VERIFY_SCRIPT!
    pause
    exit /b 1
)

echo Image:  !IMAGE!
echo Script: !VERIFY_SCRIPT!
echo.

!PYTHON_CMD! "!VERIFY_SCRIPT!" "!IMAGE!" !EXTRA_ARGS!
set VERIFY_EXIT=!ERRORLEVEL!

echo.
echo ============================================================
if !VERIFY_EXIT! EQU 0 (
    echo   Done.
) else (
    echo   Verification returned exit code !VERIFY_EXIT!.
)
echo ============================================================
echo.

pause
exit /b !VERIFY_EXIT!
