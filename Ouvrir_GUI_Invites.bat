@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=8787; $running=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue; if (-not $running) { Start-Process -FilePath python -ArgumentList @('gui_invites.py','--port','8787') -WorkingDirectory '%CD%' -WindowStyle Hidden; Start-Sleep -Milliseconds 900 }; Start-Process 'http://127.0.0.1:8787'"
