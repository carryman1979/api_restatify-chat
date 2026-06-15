#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-standalone}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8089}"

cd "$SCRIPT_DIR"

ensure_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Created .env from .env.example"
  fi
}

run_standalone() {
  ensure_env

  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi

  . .venv/bin/activate
  python -m pip install -e .

  exec python -m uvicorn src.app.main:app --app-dir "$SCRIPT_DIR" --host "$HOST" --port "$PORT" --reload
}

run_docker() {
  ensure_env

  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required for docker mode." >&2
    exit 1
  fi

  exec docker compose up --build
}

case "$MODE" in
  standalone)
    run_standalone
    ;;
  docker)
    run_docker
    ;;
  *)
    echo "Usage: ./run.sh [standalone|docker]" >&2
    exit 1
    ;;
esac
