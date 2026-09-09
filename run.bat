@echo off
REM Double-click this file to install the dependencies and start the tool.
cd /d "%~dp0"
py -m pip install -q -r requirements.txt
start "" http://127.0.0.1:8000
py -m uvicorn app:app --reload
pause
