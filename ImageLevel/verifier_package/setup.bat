@echo off
REM Setup script cho Verifier (Windows)

echo Setting up ZK-SNARK Steganography Verifier...

REM Check Node.js
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Node.js not found. Please install Node.js first.
    exit /b 1
)

REM Check npm
where npm >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: npm not found. Please install npm first.
    exit /b 1
)

REM Install snarkjs
echo Installing snarkjs...
call npm install -g snarkjs

REM Check Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found. Please install Python first.
    exit /b 1
)

REM Install Python dependencies
echo Installing Python dependencies...
call pip install -r requirements.txt

echo.
echo Setup completed!
echo.
echo You can now verify stego images with:
echo   python scripts\verify.py ^<stego_image.png^>
pause
