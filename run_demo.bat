@echo off
rem Start the Magma Policy Draft Studio demo on http://localhost:8000 (Windows).
cd /d "%~dp0"
if not exist .venv (
  echo Creating Python environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .venv\chromium_ready (
  python -m playwright install chromium
  echo ok> .venv\chromium_ready
)
if not exist web\dist (
  pushd web
  call npm install --no-audit --no-fund
  call npm run build
  popd
)
start "" http://localhost:8000
python -m uvicorn --app-dir server main:app --port 8000
