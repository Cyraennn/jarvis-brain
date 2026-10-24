@echo off
REM CYRAEN - Windows .exe derleme
setlocal
cd /d "%~dp0"

echo [1/3] Bagimliliklar...
python -m pip install -r requirements.txt || goto :err
python -m pip install pyinstaller || goto :err

echo [2/3] Varliklar (applause.wav + ikon + PWA ikonlari)...
python assets\generate_assets.py || goto :err
python assets\generate_pwa_icons.py || goto :err

echo [3/3] PyInstaller...
python -m PyInstaller --noconfirm cyraen.spec || goto :err

echo.
echo Tamamlandi:  dist\CYRAEN\CYRAEN.exe
echo Calistirmadan once dist\CYRAEN\ klasorune .env dosyanizi (GEMINI_API_KEY) kopyalayin.
copy /y ".env" "dist\CYRAEN\.env" >nul 2>&1 && echo (.env kopyalandi)
goto :eof

:err
echo HATA - derleme durduruldu.
exit /b 1
