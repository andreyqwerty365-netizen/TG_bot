@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist backups mkdir backups
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i
if exist notes.db (
  if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" tools\sqlite_online_backup.py --source notes.db --destination backups\notes_%TS%.db
  ) else (
    python tools\sqlite_online_backup.py --source notes.db --destination backups\notes_%TS%.db
  )
  if errorlevel 1 (
    echo Backup failed
    pause
    exit /b 1
  )
  echo Backup created: backups\notes_%TS%.db
) else (
  echo notes.db not found
  pause
  exit /b 1
)
pause
