@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title fioritura
set "PYEXE=%~dp0lead-parser\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"

:menu
cls
echo.
echo   ==================================================
echo              fioritura — центр управления
echo   ==================================================
echo.
echo     1   Открыть портфолио в браузере
echo     2   Запустить парсер заказов
echo     3   Пробный запуск парсера: заказы прямо в окне, без бота
echo.
echo     --- настройка, делается один раз ---
echo     4   Установить или обновить парсер
echo     5   Вписать ключи и чаты  — файл .env
echo     6   Войти в Telegram
echo     7   Узнать ID чата, куда бот будет слать заказы
echo     8   Показать мои чаты и каналы  — для TG_CHATS
echo.
echo     9   Ещё: проверить фразу, автозапуск, ярлыки
echo     0   Выход
echo.
choice /c 1234567890 /n /m "  Нажми цифру: "
if errorlevel 10 exit /b 0
if errorlevel 9 goto more
if errorlevel 8 goto chats
if errorlevel 7 goto botchat
if errorlevel 6 goto login
if errorlevel 5 goto env
if errorlevel 4 goto setup
if errorlevel 3 goto dryrun
if errorlevel 2 goto parser
if errorlevel 1 goto portfolio
goto menu

:portfolio
start "" "%~dp0index.html"
goto menu

:parser
call :need_install
if errorlevel 1 goto menu
start "fioritura — парсер" "%~dp0parser.bat"
goto menu

:dryrun
call :need_install
if errorlevel 1 goto menu
start "fioritura — пробный запуск" "%~dp0parser.bat" --dry-run
goto menu

:setup
call "%~dp0setup.bat"
goto menu

:env
if not exist "%~dp0lead-parser\.env" copy "%~dp0lead-parser\.env.example" "%~dp0lead-parser\.env" >nul
start "" notepad "%~dp0lead-parser\.env"
echo.
echo   Открыл файл настроек в Блокноте. Впиши значения, сохрани Ctrl+S и закрой.
echo.
pause
goto menu

:login
call :need_install
if errorlevel 1 goto menu
call :run_py --login
goto menu

:botchat
call :need_install
if errorlevel 1 goto menu
call :run_py --bot-chats
goto menu

:chats
call :need_install
if errorlevel 1 goto menu
call :run_py --list-chats
goto menu

:more
cls
echo.
echo     1   Проверить любую фразу: пройдёт ли она как заказ
echo     2   Автозапуск парсера вместе с Windows: включить
echo     3   Автозапуск: выключить
echo     4   Ярлыки на рабочий стол
echo     0   Назад
echo.
choice /c 12340 /n /m "  Нажми цифру: "
if errorlevel 5 goto menu
if errorlevel 4 goto shortcuts
if errorlevel 3 goto autostart_off
if errorlevel 2 goto autostart_on
if errorlevel 1 goto testphrase
goto menu

:testphrase
call :need_install
if errorlevel 1 goto more
call :run_py --test
goto more

:autostart_on
call :shortcut Startup "fioritura-parser" "%~dp0parser.bat" 7
if errorlevel 1 goto shortcut_fail
echo   Готово: при входе в Windows парсер будет запускаться свёрнутым окном.
pause
goto more

:autostart_off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\shortcut.ps1" -Folder Startup -Name "fioritura-parser" -Remove
echo   Автозапуск выключен.
pause
goto more

:shortcuts
call :shortcut Desktop "fioritura" "%~dp0START.bat" 1
if errorlevel 1 goto shortcut_fail
call :shortcut Desktop "fioritura - портфолио" "%~dp0index.html" 1
echo   Готово: на рабочем столе появились ярлыки «fioritura» и «fioritura - портфолио».
pause
goto more

:shortcut_fail
echo   Не получилось создать ярлык. Можно сделать вручную: правый клик по файлу — «Создать ярлык».
pause
goto more

rem ---------------------------------------------------------------- помощники
:need_install
if exist "%PYEXE%" exit /b 0
echo.
echo   Парсер ещё не установлен. Сначала нажми 4 — «Установить».
echo.
pause
exit /b 1

:run_py
pushd "%~dp0lead-parser"
"%PYEXE%" main.py %*
popd
echo.
pause
exit /b 0

:shortcut
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\shortcut.ps1" -Folder %1 -Name "%~2" -Target "%~3" -Style %4
exit /b %errorlevel%
