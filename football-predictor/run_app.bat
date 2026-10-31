@echo off
REM Double-click to start the Football Predictor web app.
cd /d "%~dp0"
python -m pip install --quiet -r requirements.txt
python -m streamlit run app.py
pause
