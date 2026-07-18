@echo off
rem Startet die Kurs-Anwendung (Doppelklick genuegt):
rem   1. prueft, ob Python und die Abhaengigkeiten vorhanden sind,
rem   2. oeffnet den Browser auf http://localhost:8000,
rem   3. startet den Server (Strg+C oder Fenster schliessen zum Beenden).
cd /d "%~dp0"

python --version >nul 2>&1 || (
  echo Python wurde nicht gefunden - bitte zuerst installieren: https://www.python.org
  pause
  exit /b 1
)

rem Abhaengigkeiten nur installieren, wenn sie fehlen
python -c "import yfinance, sqlalchemy" >nul 2>&1 || pip install -r requirements.txt

rem Browser erst oeffnen, wenn der Server gleich lauscht (2 s Vorsprung)
start "" cmd /c "timeout /t 2 >nul & start "" http://localhost:8000"

python server.py

rem Fenster offen halten, falls der Server mit Fehler beendet wurde
pause
