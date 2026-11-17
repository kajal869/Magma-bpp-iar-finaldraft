#!/usr/bin/env bash
# Start the Magma Policy Draft Studio demo on http://localhost:8000 (macOS / Linux).
# First run creates a virtual environment, installs dependencies, downloads Chromium and builds the web app.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

command -v python3 >/dev/null || { echo "python3 not found. Install Python 3.10+ (see USER_GUIDE_MAC.md)."; exit 1; }
command -v node    >/dev/null || { echo "node not found. Install Node.js 18+ (see USER_GUIDE_MAC.md)."; exit 1; }

if [ ! -d .venv ]; then
  echo "Creating Python environment..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing Python packages..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f .venv/.chromium_ready ]; then
  echo "Downloading the headless browser used for PDFs (once, ~150 MB)..."
  python -m playwright install chromium
  touch .venv/.chromium_ready
fi

if [ ! -d web/dist ] || [ -n "$(find web/src web/package.json -newer web/dist/index.html 2>/dev/null | head -1)" ]; then
  echo "Building the web app..."
  (cd web && npm install --no-audit --no-fund && npm run build)
fi

URL="http://localhost:${PORT}"
echo "Starting the portal at ${URL}  (press Ctrl+C to stop)"
( sleep 3; if command -v open >/dev/null; then open "$URL"; elif command -v xdg-open >/dev/null; then xdg-open "$URL"; fi ) &
exec python -m uvicorn --app-dir server main:app --port "${PORT}"
