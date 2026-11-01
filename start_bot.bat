@echo off
cd /d "%~dp0"
:: Запуск через wscript в полностью скрытом окне
wscript.exe "%~dp0run_hidden.vbs"
