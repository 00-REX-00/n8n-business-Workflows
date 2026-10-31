#!/usr/bin/env bash
# Start the Football Predictor web app.
cd "$(dirname "$0")"
python3 -m pip install --quiet -r requirements.txt
python3 -m streamlit run app.py
