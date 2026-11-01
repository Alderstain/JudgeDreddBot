@echo off
cd /d "%~dp0"
echo [Docker] Остановка контейнера Judge Dredd Bot...
docker-compose down
echo [Docker] Контейнер остановлен.
pause
