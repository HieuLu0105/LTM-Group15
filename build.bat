@echo off
REM Build NetPulse.exe (chay tren Windows, can Python 3.10+)
py -m pip install -r requirements-build.txt || goto :err
py -m PyInstaller --noconfirm --clean --onefile --name NetPulse ^
  --add-data "static;static" ^
  --add-data "libs;libs" ^
  --collect-all pythonnet ^
  --collect-all clr_loader ^
  --hidden-import clr ^
  --collect-submodules aiohttp ^
  --collect-submodules scapy ^
  app.py || goto :err
echo.
echo Xong! File exe nam o: dist\NetPulse.exe
pause
exit /b 0
:err
echo Build that bai.
pause
exit /b 1
