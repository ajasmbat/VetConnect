#!/usr/bin/env bash
# Start the VetConnect backend on http://localhost:8000
#
# Usage: ./run.sh        # dev mode with reload
#        PORT=9000 ./run.sh
#        NO_RELOAD=1 ./run.sh   # production-ish

set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

if [ ! -d ".venv" ]; then
  echo "==> Creating virtualenv"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import fastapi" 2>/dev/null; then
  echo "==> Installing dependencies"
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
fi

if [ ! -f ".env" ]; then
  if [ -f "../.env.example" ]; then
    echo "==> No .env found — copying .env.example. Edit backend/.env and set VA_API_KEY."
    cp ../.env.example .env
  else
    echo "!! .env not found and no .env.example to copy from." >&2
    exit 1
  fi
fi

# Warn (don't fail) if the key still looks like the placeholder.
if grep -qE '^VA_API_KEY=(your_va_sandbox_key_here|)?\s*$' .env; then
  echo "!! Warning: VA_API_KEY in backend/.env is empty or still the placeholder."
  echo "   Get a free key at https://developer.va.gov/apply and paste it in."
fi

RELOAD_FLAG="--reload"
if [ "${NO_RELOAD:-0}" = "1" ]; then
  RELOAD_FLAG=""
fi

echo "==> Starting uvicorn on http://${HOST}:${PORT}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" $RELOAD_FLAG
