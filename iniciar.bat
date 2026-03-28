@echo off
echo Cerrando procesos anteriores...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM python3.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo Iniciando servidor...
cd /d "%~dp0"
venv\Scripts\uvicorn main:app --reload --port 8000
pause
