# 0017. Technology stack

Status: Accepted · Date: 2026-11-22

## Context

We need a stack that suits AI work, typed interfaces, a web front end and simple on-premises deployment. The team is comfortable with Python.

## Decision

| Area | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, pydantic v2, managed with uv |
| Our database | SQLAlchemy 2 and Alembic on Postgres (see 0011) |
| Frontend | A React, Vite and TypeScript single-page app |
| Proxy | Caddy |
| Deployment | Docker Compose (see 0012) |
| Tenancy | One company per install. No multi-tenancy. |

## Consequences

Good:

- Python has the strongest AI ecosystem. pydantic gives typed schemas for tools and APIs.
- The frontend builds to static files, so production needs no Node server.
- One company per install keeps data isolation simple.

Bad:

- Python is slower than some alternatives. That does not matter at single-company scale.
- Moving to multiple companies per install later would mean significant rework.

## Alternatives considered

- TypeScript on the backend. Rejected: the AI ecosystem is weaker and the team prefers Python.
- Next.js with server rendering. Rejected: it adds a Node server with no benefit for a LAN app.
- Multi-tenancy. Rejected: each install serves one company.
