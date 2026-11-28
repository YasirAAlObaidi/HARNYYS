# yyai

yyai is an agentic AI system that we install on-premises for one client company at a time. Each install answers customers and staff, reads from the client's business software (accounting, inventory, CRM, POS) and, where a project allows it, writes back through purpose-built tools. We are launching in the UAE first, and WhatsApp is the main customer channel.

## Developer setup (Mac)

```
scripts/setup-mac.sh
```

The script installs Docker through Colima, along with Docker Compose, Buildx and uv, all from Homebrew. It then starts the dev Postgres from `deploy/compose.dev.yaml` on `127.0.0.1:55432` and installs the Python environment. You can run it again safely: it skips anything that is already done. Afterwards, check everything:

```
cd apps/server && uv run pytest -q && uv run lint-imports
cd apps/web && npm run lint && npm test && npm run build
```

To run the whole system in Docker, see `deploy/README.md`. The staff web app is in `apps/web` (see its README).

## How the docs are organised

| Where | What it holds |
|---|---|
| `docs/index.html` | The architecture overview. Open it in a browser. |
| `docs/flows/price-request.html` | Animated walk-through of a customer asking a price, from incoming message to reply. |
| `docs/flows/stock-import.html` | Animated walk-through of a staff member importing a stock sheet into the ERP. |
| `docs/flows/connection-vs-job.html` | Animated explanation of why integrations are grouped by job, not by connection type. |
| `docs/decisions/` | One Markdown record per architecture decision, with context, consequences and the options we rejected. Start at `docs/decisions/README.md`. |
