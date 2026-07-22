# api_restatify-chat

Public Support Chat API for Restatify support operations.

Current release: v0.2.1

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

## Production Architecture

- The Support API is the public endpoint for mobile and desktop clients.
- WordPress and the Support API can run on two separate servers with their own public IPs and FQDNs.
- Production integration uses a private HTTP WordPress bridge for server-to-server operations.
- The legacy local `wp-load.php` bridge remains a development fallback only.

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

## Production reverse proxy (dedicated chat Caddy)

Keep Booking API proxy untouched by running a separate Caddy service from this repository.

1. Copy proxy environment template and fill server-local values:

```bash
cp .env.proxy.example .env.proxy
```

2. Start API + dedicated Caddy proxy:

```bash
docker compose --env-file .env.proxy -f docker-compose.prod.yml up -d --build
```

3. Verify listeners and health:

```bash
ss -ltnp | egrep '(:443|:8089)'
curl -fsS http://127.0.0.1:8089/health
curl -fsS https://api.example.test/health
```

Notes:

- `SUPPORT_API_PUBLIC_BIND_IP` should be the API server public IP to avoid 443 conflicts with VPN-bound services.
- `deploy/Caddyfile.support-api.example` proxies TLS traffic to `api-chat:8089` over the Docker network.

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
- For split-server production, set `WP_BRIDGE_BASE_URL` and `WP_BRIDGE_API_KEY` so the API reaches the private WordPress bridge endpoint.

## Release Notes

### v0.2.1

- Added HTTP-based private WordPress bridge support for split-server production deployments.
- Preserved the public Support API endpoint for apps while moving WordPress operations behind a private server-to-server boundary.
- Added bridge configuration settings and tests for the new remote bridge path.

### v0.2.0

- Added support WebSocket update stream with reconnect-friendly event payloads.
- Added store-delta watcher to publish visitor message and inactivity deletion updates.
- Expanded support API operations (messages, AI mode, delete, booking trigger).
- Hardened API key lifecycle and bridge-backed validation path.
