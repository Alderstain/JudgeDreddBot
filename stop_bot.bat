@echo off
echo Остановка фонового процесса бота JudgeDredd...
wmic process where "name='pythonw.exe' and commandline like '%%main.py%%'" call terminate >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
)
echo Бот успешно остановлен.
pause
