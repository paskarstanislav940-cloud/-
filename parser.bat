@echo off
chcp 65001 >nul
setlocal
title fioritura — парсер заказов
cd /d "%~dp0lead-parser"
set "PYTHONUTF8=1"
set "PYEXE=%~dp0lead-parser\.venv\Scripts\python.exe"

if exist "%PYEXE%" goto check_env
echo.
echo   Парсер ещё не установлен. Открой START.bat и нажми 4.
echo.
pause
exit /b 1

:check_env
if exist ".env" goto run
copy ".env.example" ".env" >nul

:run
echo.
echo   Парсер работает. Найденные заказы приходят в твоего Telegram-бота.
echo   Остановить — просто закрой это окно.
echo.
"%PYEXE%" main.py %*
if errorlevel 1 goto crashed
echo.
echo   Парсер остановлен.
pause
exit /b 0

:crashed
echo.
echo   Парсер остановился с ошибкой — она выше. Перезапущу через 20 секунд.
echo   Если перезапуск не нужен — закрой окно.
timeout /t 20
goto run
