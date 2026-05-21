@echo off
title NetNavi OS — API Key Setup
color 0B
echo.
echo  =================================================
echo   NetNavi OS — API Key Configuration
echo  =================================================
echo.
echo  You will need a FREE Pinecone account to give
echo  your Navi long-term memory across sessions.
echo.
echo  Get your key at: https://pinecone.io
echo   1. Create a free account
echo   2. Create an index
echo   3. Copy your API key and paste it below
echo.
echo  (You can press ENTER to skip for now)
echo.

set /p PINECONE_KEY=" Pinecone API Key: "

if not "%PINECONE_KEY%"=="" (
    if not exist "usr_config" mkdir usr_config
    echo PINECONE_API_KEY=%PINECONE_KEY%> usr_config\pinecone_credentials.env
    echo.
    echo  ✅ Pinecone key saved to usr_config\pinecone_credentials.env
) else (
    echo.
    echo  Skipped. You can run this again later to add your key.
)

echo.
echo  =================================================
echo   Done! Your Navi's memory is configured.
echo  =================================================
echo.
pause
