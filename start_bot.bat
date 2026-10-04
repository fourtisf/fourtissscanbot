@echo off
REM Windows: jalankan bot dan otomatis restart kalau berhenti/crash.
REM Taruh shortcut file ini di folder shell:startup supaya ikut jalan saat Windows nyala.
cd /d "%~dp0"
:loop
echo [%date% %time%] Starting bot...
python telegram_bot.py
echo [%date% %time%] Bot berhenti, restart dalam 10 detik...
timeout /t 10 /nobreak >nul
goto loop
