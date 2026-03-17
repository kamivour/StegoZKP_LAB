@echo off
setlocal enabledelayedexpansion

REM =============================================================================
REM  ZK-SNARK DICOM Steganography -- Verifier Setup Script (Windows)
REM =============================================================================
REM  Checks every required dependency and installs missing ones automatically.
REM
REM  Requirements:
REM    Python  >= 3.9     (pydicom, Pillow, numpy, scipy)
REM    Node.js >= 18
REM    snarkjs >= 0.7.6
REM    verification_key.json  (must be placed here by the image sender)
REM =============================================================================

set ERRORS=0
set SCRIPT_DIR=%~dp0
REM Remove trailing backslash
if "!SCRIPT_DIR:~-1!"=="\" set SCRIPT_DIR=!SCRIPT_DIR:~0,-1!

echo.
echo ============================================================
echo   ZK-SNARK DICOM Steganography -- Verifier Dependency Setup
echo ============================================================
echo.

REM =============================================================================
REM  1. PYTHON >= 3.9
REM =============================================================================
echo --- [1/4] Python 3.9+ ---

set PYTHON_CMD=
set PYTHON_VER=

REM Try each candidate command
for %%P in (python3 python py) do (
    if "!PYTHON_CMD!"=="" (
        where %%P >nul 2>nul
        if !ERRORLEVEL! EQU 0 (
            for /f "tokens=2" %%V in ('%%P --version 2^>^&1') do (
                set RAW_VER=%%V
                for /f "tokens=1,2 delims=." %%A in ("%%V") do (
                    if %%A GEQ 3 (
                        if %%B GEQ 9 (
                            set PYTHON_CMD=%%P
                            set PYTHON_VER=%%V
                        )
                    )
                )
            )
        )
    )
)

if not "!PYTHON_CMD!"=="" (
    echo [OK]   Python !PYTHON_VER! found
) else (
    echo [WARN] Python 3.9+ not found. Attempting install via winget...
    winget install --id Python.Python.3.12 --source winget --silent --accept-package-agreements --accept-source-agreements >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        echo [OK]   Python 3.12 installed via winget.
        echo [INFO] Re-open this terminal to pick up the updated PATH, then re-run setup.bat.
        REM Attempt to use py launcher which may already be on PATH
        where py >nul 2>nul
        if !ERRORLEVEL! EQU 0 (
            set PYTHON_CMD=py
            echo [OK]   Using Python Launcher 'py' for this session.
        )
    ) else (
        echo [WARN] winget install failed. Trying Python Launcher...
        where py >nul 2>nul
        if !ERRORLEVEL! EQU 0 (
            set PYTHON_CMD=py
            echo [OK]   Found Python Launcher 'py'
        ) else (
            echo [ERR]  Python 3.9+ not found and auto-install failed.
            echo        Download manually: https://www.python.org/downloads/
            echo        Check "Add Python to PATH" during installation.
            set /a ERRORS+=1
        )
    )
)

REM =============================================================================
REM  2. PYTHON PACKAGES
REM =============================================================================
echo.
echo --- [2/4] Python packages ---

if not "!PYTHON_CMD!"=="" (
    set PKG_MISSING=0

    for %%K in (pydicom PIL numpy scipy) do (
        !PYTHON_CMD! -c "import %%K" >nul 2>nul
        if !ERRORLEVEL! EQU 0 (
            echo [OK]   %%K
        ) else (
            echo [WARN] %%K -- not found
            set PKG_MISSING=1
        )
    )

    if !PKG_MISSING! EQU 1 (
        echo [INFO] Installing missing packages from requirements.txt...
        !PYTHON_CMD! -m pip install --upgrade -r "!SCRIPT_DIR!\requirements.txt"
        if !ERRORLEVEL! NEQ 0 (
            echo [ERR]  pip install failed.
            echo        Try running this script as Administrator, or run manually:
            echo          pip install pydicom Pillow numpy scipy
            set /a ERRORS+=1
        ) else (
            REM Re-verify
            for %%K in (pydicom PIL numpy scipy) do (
                !PYTHON_CMD! -c "import %%K" >nul 2>nul
                if !ERRORLEVEL! EQU 0 (
                    echo [OK]   %%K installed
                ) else (
                    echo [ERR]  %%K still missing after install
                    set /a ERRORS+=1
                )
            )
        )
    )
) else (
    echo [WARN] Skipping package check -- Python unavailable.
)

REM =============================================================================
REM  3. NODE.JS >= 18
REM =============================================================================
echo.
echo --- [3/4] Node.js 18+ ---

set NODE_OK=0
set NODE_VER=

where node >nul 2>nul
if !ERRORLEVEL! EQU 0 (
    for /f "delims=" %%V in ('node -e "process.stdout.write(process.version)" 2^>nul') do set NODE_VER=%%V
    REM Extract major version: strip leading 'v' then take part before first '.'
    set NODE_MAJ=!NODE_VER:v=!
    for /f "tokens=1 delims=." %%M in ("!NODE_MAJ!") do set NODE_MAJ=%%M
    if !NODE_MAJ! GEQ 18 (
        echo [OK]   Node.js !NODE_VER!
        set NODE_OK=1
    ) else (
        echo [WARN] Node.js !NODE_VER! found but version 18+ required.
    )
)

if !NODE_OK! EQU 0 (
    echo [INFO] Attempting to install Node.js LTS via winget...
    winget install --id OpenJS.NodeJS.LTS --source winget --silent --accept-package-agreements --accept-source-agreements
    if !ERRORLEVEL! EQU 0 (
        echo [OK]   Node.js LTS installed.
        echo [INFO] PATH will update in a new terminal session. Re-run setup.bat after reopening.
        REM Try refreshing PATH from registry for this session
        for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set SYS_PATH=%%B
        if defined SYS_PATH set PATH=!SYS_PATH!;!PATH!
        where node >nul 2>nul
        if !ERRORLEVEL! EQU 0 (
            for /f "delims=" %%V in ('node -e "process.stdout.write(process.version)" 2^>nul') do (
                echo [OK]   Node.js %%V active in this session
                set NODE_OK=1
            )
        )
    ) else (
        echo [ERR]  Node.js 18+ not found and auto-install failed.
        echo        Download manually: https://nodejs.org/en/download
        echo        Choose the LTS installer (v18.x or later).
        set /a ERRORS+=1
    )
)

REM =============================================================================
REM  4. SNARKJS >= 0.7.6
REM =============================================================================
echo.
echo --- [4/4] snarkjs 0.7.6+ ---

set SNARKJS_OK=0

where snarkjs >nul 2>nul
if !ERRORLEVEL! EQU 0 (
    for /f "tokens=*" %%V in ('snarkjs --version 2^>nul') do (
        REM %%V is something like "snarkjs@0.7.4" or just "0.7.4"
        set SJS_RAW=%%V
        REM Extract version number: strip everything up to last '@' or space
        for %%T in (!SJS_RAW!) do set SJS_VER=%%T
        set SJS_VER=!SJS_VER:snarkjs@=!

        for /f "tokens=1,2,3 delims=." %%A in ("!SJS_VER!") do (
            set SJS_MAJ=%%A
            set SJS_MIN=%%B
            set SJS_PAT=%%C
        )
        REM Check >= 0.7.6
        set VER_OK=0
        if !SJS_MAJ! GTR 0 set VER_OK=1
        if !SJS_MAJ! EQU 0 if !SJS_MIN! GTR 7 set VER_OK=1
        if !SJS_MAJ! EQU 0 if !SJS_MIN! EQU 7 if !SJS_PAT! GEQ 6 set VER_OK=1

        if !VER_OK! EQU 1 (
            echo [OK]   snarkjs !SJS_VER!
            set SNARKJS_OK=1
        ) else (
            echo [WARN] snarkjs !SJS_VER! found but 0.7.6+ required. Upgrading...
        )
    )
)

if !SNARKJS_OK! EQU 0 (
    echo [INFO] Installing/upgrading snarkjs...
    call npm install -g snarkjs
    if !ERRORLEVEL! EQU 0 (
        for /f "tokens=*" %%V in ('snarkjs --version 2^>nul') do echo [OK]   snarkjs %%V installed
        set SNARKJS_OK=1
    ) else (
        echo [ERR]  snarkjs installation failed.
        echo        Ensure Node.js/npm is working, then run: npm install -g snarkjs
        set /a ERRORS+=1
    )
)

REM =============================================================================
REM  5. VERIFICATION ARTIFACTS
REM =============================================================================
echo.
echo --- Verification artifacts ---

set KEY_FILE=!SCRIPT_DIR!\circuits\compiled\build\chaos_zk_stego_verification_key.json
if exist "!KEY_FILE!" (
    echo [OK]   verification_key.json found
) else (
    echo [WARN] verification_key.json not found at:
    echo        !KEY_FILE!
    echo        Obtain this file from the image sender and place it at the path above.
)

set CHAOS_KEY=!SCRIPT_DIR!\chaos_key.txt
if exist "!CHAOS_KEY!" (
    echo [OK]   chaos_key.txt found
) else (
    echo [WARN] chaos_key.txt not found -- required for full metadata extraction.
    echo        Not required for public-auditor ZK verification only.
)

REM =============================================================================
REM  SUMMARY
REM =============================================================================
echo.
echo ============================================================
if !ERRORS! EQU 0 (
    echo   All dependencies satisfied.
    echo.
    echo   Public-auditor ZK verification:
    echo     python scripts\verify.py ^<stego_image.png^>
    echo.
    echo   Authorized recipient (metadata + RDH restore):
    echo     python scripts\dicom_extract.py ^<stego_image.png^> --restore-output restored.png
) else (
    echo   Setup finished with !ERRORS! error(s).
    echo   Fix the issues listed above before proceeding.
)
echo ============================================================
echo.

if !ERRORS! GTR 0 (
    pause
    exit /b !ERRORS!
)
pause
