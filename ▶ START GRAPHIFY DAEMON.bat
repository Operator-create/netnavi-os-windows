@echo off
echo =================================================
echo  🌐 NetNavi OS - Graphify Watch Daemon 🌐
echo =================================================
echo.
echo Installing Watchdog dependency...
python -m pip install watchdog --quiet
echo.
echo Starting Graphify Background Daemon...
echo It will watch your Vault for changes and update the semantic graph automatically.
start /B graphify watch . > graphify-watch.log 2>&1
echo.
echo ✅ Daemon is running in the background. You can safely close this window.
pause
