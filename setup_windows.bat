@echo off
REM One-time setup on Windows: creates a virtual environment and installs dependencies
cd /d %~dp0
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Installing Google TimesFM (AI forecasting model, downloads PyTorch - this can take several minutes)...
pip install "timesfm[torch]"
if errorlevel 1 (
  echo TimesFM could not be installed. The app still works; the report will say TimesFM is not installed.
)
if not exist .env copy .env.example .env
echo.
echo Setup done.
echo 1. Edit .env: SUPABASE_URL, SUPABASE_ANON_KEY, DATABASE_URL (Session pooler string) and GEMINI_API_KEY
echo    (see docs\SETUP_SUPABASE.md)
echo 2. Tables are created automatically on the first start
echo 3. Start the app with run_app.bat
pause
