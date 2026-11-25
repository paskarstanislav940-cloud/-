@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
title fioritura — установка
echo.
echo   Установка парсера заказов fioritura
echo   -----------------------------------
echo.

rem ---- 1. Ищем Python 3.10 или новее -------------------------------------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto have_python

echo   Python не найден. Он нужен, чтобы работал парсер.
echo.
where winget >nul 2>&1
if errorlevel 1 goto manual_python
echo     1   Установить Python автоматически — рекомендую
echo     2   Я установлю сам с сайта python.org
echo.
choice /c 12 /n /m "  Нажми цифру: "
if errorlevel 2 goto manual_python
echo.
echo   Ставлю Python 3.12. Если Windows спросит разрешение — нажми «Да».
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto manual_python
echo.
echo   Python установлен.
echo   ВАЖНО: закрой это окно, снова открой START.bat и ещё раз нажми 4.
echo   Так Windows «увидит» новый Python.
echo.
pause
exit /b 0

:manual_python
echo.
echo   Сейчас откроется сайт python.org. Скачай Python для Windows и установи.
echo   При установке ОБЯЗАТЕЛЬНО поставь галочку «Add python.exe to PATH».
echo   Потом снова открой START.bat и нажми 4.
echo.
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1

:have_python
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do echo   Нашёл %%v
echo.

rem ---- 2. Отдельная «коробка» для библиотек парсера ----------------------
if exist "lead-parser\.venv\Scripts\python.exe" goto have_venv
echo   Создаю окружение для парсера...
%PY% -m venv "lead-parser\.venv"
if errorlevel 1 goto fail
:have_venv

rem ---- 3. Библиотеки ------------------------------------------------------
echo   Скачиваю библиотеки, это займёт минуту-две...
"lead-parser\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -U pip setuptools wheel
if errorlevel 1 goto fail
"lead-parser\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "lead-parser\requirements.txt"
if errorlevel 1 goto fail

rem ---- 4. Файл настроек --------------------------------------------------
if exist "lead-parser\.env" goto have_env
copy "lead-parser\.env.example" "lead-parser\.env" >nul
echo   Создал файл настроек lead-parser\.env
:have_env

rem ---- 5. Проверка, что всё запускается -----------------------------------
pushd lead-parser
".venv\Scripts\python.exe" main.py --test "Нужен лендинг для запуска, бюджет есть, срочно" >nul 2>&1
set "CHECK=%errorlevel%"
popd
if not "%CHECK%"=="0" goto fail

echo.
echo   ==============================================
echo     Готово! Парсер установлен и работает.
echo   ==============================================
echo.
echo   Дальше в START.bat по порядку:
echo     5 — впиши ключи и чаты
echo     6 — войди в Telegram
echo     7 — узнай ID чата для бота и впиши его в настройки
echo     3 — пробный запуск, потом 2 — настоящий
echo.
pause
exit /b 0

:fail
echo.
echo   Что-то пошло не так — сообщение об ошибке выше.
echo   Частые причины: нет интернета, антивирус блокирует скачивание.
echo   Попробуй ещё раз. Если не помогает — пришли скриншот этого окна.
echo.
pause
exit /b 1
