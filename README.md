# api_restatify-chat

Public Support Chat API for Restatify support operations.

## Goals

- Provide secure, mobile-friendly support chat endpoints outside WP-Admin.
- Keep WordPress plugin integration minimal and backward compatible.
- Reuse shared foundations from `shared_restatify-api` after first runnable release.

## Current MVP Scope

- Health endpoint
- Auth stub endpoint (to be replaced with full MFA flow)
- Support conversation list and reply stubs
- API key middleware helper

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

## Run (docker)

```bash
docker compose up --build
```

## Endpoints (initial)

- `GET /health`
- `POST /v1/auth/login`
- `GET /v1/support/conversations`
- `POST /v1/support/conversations/{conversation_id}/reply`

## Notes

- This is the initial scaffold for implementation start.
- Security and auth are intentionally minimal placeholders and will be hardened next.
