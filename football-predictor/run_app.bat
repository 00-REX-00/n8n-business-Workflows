@echo off
REM Double-click to start the Football Predictor web app.
cd /d "%~dp0"
set PY=python
python --version >nul 2>nul || set PY=py
%PY% --version >nul 2>nul || (echo Python not found. Install Python 3.12 from python.org and tick "Add python.exe to PATH". & pause & exit /b 1)
echo Installing requirements (the first time takes a few minutes)...
%PY% -m pip install --quiet -r requirements.txt || (echo Package install failed - see the error above. & pause & exit /b 1)
echo Starting the app. Your browser will open http://localhost:8501 - keep this window open.
start "" cmd /c "timeout /t 10 /nobreak >nul & start http://localhost:8501"
%PY% -m streamlit run app.py
pause
