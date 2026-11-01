@echo off
cd /d "%~dp0"
echo [Docker] Просмотр логов (нажмите Ctrl+C для выхода)...
docker-compose logs -f judge-dredd-bot
