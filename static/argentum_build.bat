@echo off
REM Argentum Browser - Build PKG Script
REM Place this file in C:\PS4Tools\ alongside orbis-pub-gen.exe

echo ============================================
echo Argentum Browser PKG Builder
echo ============================================
echo.

REM Download browser file
echo [1/3] Downloading Argentum Browser...
curl -s "http://192.168.0.238:8765/browser" -o "C:\PS4Tools\argentum_browser.html"

if not exist "C:\PS4Tools\argentum_browser.html" (
    echo ERROR: Failed to download browser!
    echo Make sure server is running at 192.168.0.238:8765
    pause
    exit /b 1
)

echo Browser downloaded successfully.

REM Download GP4 project file
echo [2/3] Downloading project file...
curl -s "http://192.168.0.238:8765/static/argentum.gp4" -o "C:\PS4Tools\argentum.gp4"

if not exist "C:\PS4Tools\argentum.gp4" (
    echo ERROR: Failed to download GP4!
    pause
    exit /b 1
)

echo Project file downloaded.

REM Build PKG using orbis-pub-cmd
echo [3/3] Building PKG...
echo.

cd C:\PS4Tools

if exist "orbis-pub-cmd.exe" (
    orbis-pub-cmd.exe --build "C:\PS4Tools\argentum.gp4" --output "C:\PS4Tools\output\"
) else (
    echo ERROR: orbis-pub-cmd.exe not found!
    echo Please run orbis-pub-gen.exe and open argentum.gp4 manually
    echo Then go to Command -^> Build PKG
    pause
    exit /b 1
)

if exist "C:\PS4Tools\output\argentum.pkg" (
    echo.
    echo ============================================
    echo SUCCESS! PKG created!
    echo Location: C:\PS4Tools\output\argentum.pkg
    echo ============================================
    echo.
    echo Transfer to PS4 via FTP and install.
) else (
    echo.
    echo PKG not found. Try building manually:
    echo 1. Open argentum.gp4 in orbis-pub-gen.exe
    echo 2. Command -^> Build PKG
)

pause
