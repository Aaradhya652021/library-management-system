@echo off
cd /d "%~dp0"
echo Starting the Library website with a public Cloudflare tunnel...
echo Keep this window open. Press Ctrl+C to stop the public site.
echo.
.venv\Scripts\python.exe scripts\run_public.py
echo.
echo The public site has stopped.
pause
