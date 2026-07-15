# api_restatify-chat

Public Support Chat API for Restatify support operations.

## Goals

- Provide secure, mobile-friendly support chat endpoints outside WP-Admin.
- Keep WordPress plugin integration minimal and backward compatible.
- Reuse shared foundations from `shared_restatify-api` after first runnable release.

## Current MVP Scope

- Health endpoint
- WordPress credential login and support API key generation
- Support conversation list and message retrieval via WordPress bridge
- Support reply, AI mode, booking overlay trigger, and delete operations
- WebSocket updates for message and conversation events
- API key middleware with WordPress-backed key validation

## Run (local)

1. Copy `.env.example` to `.env` and set `API_KEY`.
2. Install dependencies:

```bash
pip install -e .
```

3. Start API:

```bash
uvicorn src.app.main:app --host 0.0.0.0 --port 8089 --reload
```

## Scripted setup and run (recommended)

The repository now includes scripts for both standalone Python execution and Docker.

### Linux/macOS (bash)

Install dependencies / prepare runtime:

```bash
./install.sh standalone
```

Start standalone API:

```bash
./run.sh standalone
```

Build/start with Docker:

```bash
./install.sh docker
./run.sh docker
```

### Windows (PowerShell)

Install dependencies / prepare runtime:

```powershell
.\install.ps1 -Mode standalone
```

Start standalone API:

```powershell
.\run.ps1 -Mode standalone
```

Build/start with Docker:

```powershell
.\install.ps1 -Mode docker
.\run.ps1 -Mode docker
```

### Notes

- If `.env` is missing, scripts auto-create it from `.env.example`.
- Default standalone bind: `127.0.0.1:8089`.
- On Linux/macOS, make scripts executable once: `chmod +x install.sh run.sh`.

## Run (docker)

```bash
docker compose up --build
```

## Endpoints (initial)

- `GET /health`
- `POST /v1/auth/login`
- `POST /v1/auth/generate-api-key`
- `GET /v1/support/conversations`
- `GET /v1/support/conversations/{conversation_id}/messages`
- `POST /v1/support/conversations/{conversation_id}/reply`
- `PUT /v1/support/conversations/{conversation_id}/ai-mode`
- `DELETE /v1/support/conversations/{conversation_id}`
- `GET /v1/support/ws/updates`

## Notes

- API behavior now follows the WordPress chat store as source of truth.
- Local Docker setup is Rancher Desktop compatible via `docker compose`.

## Release Notes

### v0.2.0

- Added support WebSocket update stream with reconnect-friendly event payloads.
- Added store-delta watcher to publish visitor message and inactivity deletion updates.
- Expanded support API operations (messages, AI mode, delete, booking trigger).
- Hardened API key lifecycle and bridge-backed validation path.
