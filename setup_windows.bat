@echo off
REM One-time setup on Windows: creates a virtual environment and installs dependencies
cd /d %~dp0
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup done. Now edit .env with your Supabase, Gemini and RAGFlow keys, then run run_app.bat
pause
