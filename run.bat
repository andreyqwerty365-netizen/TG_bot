@echo off
chcp 65001 >nul
title Telegram Reminder Bot
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo [1/5] Подготовка конфигурации...
if not exist ".env" (
  (
    echo BOT_TOKEN=
    echo BOT_DB_PATH=notes.db
    echo BOT_LOG_LEVEL=INFO
    echo BOT_LOG_PATH=logs\bot.log
    echo BOT_INTERACTION_LOG_PATH=logs\interactions.log
    echo BOT_DEFAULT_TZ_MINUTES=0
    echo BOT_ALLOWED_USER_IDS=
    echo BOT_TRAINER_DB_PATH=workouts.sqlite3
    echo BOT_EXERCISES_PATH=exercises.json
    echo BOT_TRAINER_TIMEZONE=Europe/Moscow
  ) > ".env"
)

call :load_env
if "!BOT_TOKEN!"=="" (
  echo.
  set /p BOT_TOKEN=Вставь токен бота и нажми Enter: 
  if "!BOT_TOKEN!"=="" (
    echo [ERROR] Пустой токен. Запуск отменён.
    pause
    exit /b 1
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p='.env';$c=Get-Content $p -ErrorAction SilentlyContinue; if(-not $c){$c=@('BOT_TOKEN=','BOT_DB_PATH=notes.db','BOT_LOG_LEVEL=INFO','BOT_LOG_PATH=logs\\bot.log','BOT_INTERACTION_LOG_PATH=logs\\interactions.log','BOT_DEFAULT_TZ_MINUTES=0','BOT_ALLOWED_USER_IDS=')}; $found=$false; $out=@(); foreach($line in $c){ if($line -match '^[ ]*BOT_TOKEN='){ $out += ('BOT_TOKEN=' + $env:BOT_TOKEN); $found=$true } else { $out += $line } }; if(-not $found){ $out = @('BOT_TOKEN=' + $env:BOT_TOKEN) + $out }; [System.IO.File]::WriteAllLines($p,$out,(New-Object System.Text.UTF8Encoding($false)))"
  if errorlevel 1 (
    echo [ERROR] Не удалось сохранить токен в .env
    pause
    exit /b 1
  )
)

echo [2/5] Проверка Python...
if "!BOT_ALLOWED_USER_IDS!"=="" (
  echo.
  set /p BOT_ALLOWED_USER_IDS=Вставь Telegram user ID владельца и нажми Enter: 
  if "!BOT_ALLOWED_USER_IDS!"=="" (
    echo [ERROR] Пустой BOT_ALLOWED_USER_IDS. Запуск отменён.
    pause
    exit /b 1
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p='.env';$c=Get-Content $p -ErrorAction SilentlyContinue;$found=$false;$out=@();foreach($line in $c){if($line -match '^[ ]*BOT_ALLOWED_USER_IDS='){$out += ('BOT_ALLOWED_USER_IDS=' + $env:BOT_ALLOWED_USER_IDS);$found=$true}else{$out += $line}};if(-not $found){$out += ('BOT_ALLOWED_USER_IDS=' + $env:BOT_ALLOWED_USER_IDS)};[System.IO.File]::WriteAllLines($p,$out,(New-Object System.Text.UTF8Encoding($false)))"
  if errorlevel 1 (
    echo [ERROR] Не удалось сохранить BOT_ALLOWED_USER_IDS в .env
    pause
    exit /b 1
  )
)

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    echo [ERROR] Python не найден в PATH.
    echo Установи Python и включи опцию Add Python to PATH.
    pause
    exit /b 1
  )
)

echo [3/5] Проверка виртуального окружения...
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Создаю .venv...
  %PY% -m venv .venv || (pause & exit /b 1)
)

set "VPY=.venv\Scripts\python.exe"

echo [4/5] Установка зависимостей...
if not exist "logs" mkdir logs
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt || (pause & exit /b 1)

echo [5/5] Запуск бота...
"%VPY%" main.py

echo.
echo [INFO] Бот завершил работу.
pause
exit /b 0

:load_env
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  set "K=%%A"
  set "V=%%B"
  if defined K if not "!K:~0,1!"=="#" if not "!K!"=="" set "!K!=!V!"
)
exit /b 0
