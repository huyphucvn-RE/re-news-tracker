@echo off
REM Starts the news tracker quietly every time you log in to Windows.
REM It fetches news every hour and is reachable at http://localhost:8765 (and from your phone on the same Wi-Fi).
cd /d "%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "PYW=pythonw"
where pythonw >nul 2>nul || set "PYW=pyw"
(
  echo @echo off
  echo cd /d "%~dp0"
  echo start "" %PYW% tracker.py background
) > "%STARTUP%\RE-News-Tracker.bat"
start "" %PYW% tracker.py background
echo.
echo Done. The tracker now starts by itself when you log in, and it is running now.
echo Open http://localhost:8765 in your browser (bookmark it).
echo If Windows asks whether Python may use the network, tick "Private networks" so your phone can reach it.
echo To undo, run uninstall-autostart-windows.bat
pause
