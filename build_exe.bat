@echo off
cd /d %~dp0
python -m pip install -r requirements.txt
pyinstaller --onefile --name TelegramNotesBot main.py
pause
