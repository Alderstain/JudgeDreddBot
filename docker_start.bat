@echo off
cd /d "%~dp0"
echo [Docker] Сборка и запуск Judge Dredd Bot...
docker-compose up -d --build
echo.
echo [Docker] Контейнер успешно запущен в фоновом режиме!
echo Для просмотра логов запустите docker_logs.bat
pause
