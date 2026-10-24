@echo off
rem CYRAEN gelen kutusu temizligi - 07:30'a kadar agir agir calisir (arka planda, pencere yok).
rem Onemsiz mailler Cop kutusuna tasinir (30 gun geri alinabilir). Ilerleme: data\email_cleanup\temizlik.log
cd /d "%~dp0"
start "" "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" "%~dp0scripts\email_cleanup.py" --until 07:30
echo CYRAEN mail temizligi basladi (07:30'a kadar). Bu pencereyi kapatabilirsin.
timeout /t 5 >nul
