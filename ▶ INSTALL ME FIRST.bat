@echo off
title NetNavi OS — Installation
color 0B
echo.
echo  =================================================
echo   Welcome to NetNavi OS for Windows
echo   Your personal AI companion is about to boot.
echo  =================================================
echo.
echo  This installer will set up everything you need:
echo   - Python  (the Navi's brain runtime)
echo   - Node.js (the action layer)
echo   - Obsidian (your vault interface)
echo   - Gemini CLI (the AI action bridge)
echo.
echo  Please do NOT close this window.
echo.
pause

:: Run the PowerShell installer with execution policy bypass
powershell.exe -ExecutionPolicy Bypass -File "%~dp0install.ps1"

echo.
echo  =================================================
echo   Installation complete!
echo   Now open START_HERE.md for your next steps.
echo  =================================================
echo.
pause
