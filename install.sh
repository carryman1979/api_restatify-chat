#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-standalone}"

cd "$SCRIPT_DIR"

ensure_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Created .env from .env.example"
  fi
}

install_standalone() {
  ensure_env

  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi

  . .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -e .

  echo "Standalone installation complete."
}

install_docker() {
  ensure_env

  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required for docker mode." >&2
    exit 1
  fi

  docker compose build
  echo "Docker image build complete."
}

case "$MODE" in
  standalone)
    install_standalone
    ;;
  docker)
    install_docker
    ;;
  all)
    install_standalone
    install_docker
    ;;
  *)
    echo "Usage: ./install.sh [standalone|docker|all]" >&2
    exit 1
    ;;
esac

echo "Done. Use ./run.sh [standalone|docker] to start the API."
