# 0001. Modular monolith

Status: Accepted · Date: 2026-11-22

## Context

yyai has distinct parts: an API, business logic, an agent, integrations with client software, and our own database. We want those parts kept apart so each can change without breaking the others. A small team will install and maintain this on many client sites, often on a single machine.

## Decision

The backend is one codebase and one process. Its parts are kept apart by package boundaries and enforced import rules (see 0002), not by network calls.

Only these run as separate processes:

- Caddy, the reverse proxy that serves HTTPS and the web app.
- The server, which handles API requests.
- The worker, the same image with a different entrypoint, which runs agent turns and scheduled jobs.
- Postgres.
- The model server, which runs outside our image (see 0004).
- cloudflared, the per-client tunnel for incoming webhooks (see 0009).

## Consequences

Good:

- Calls between parts are ordinary function calls: fast, typed and easy to debug.
- One image to build, ship and update per release.
- Fewer containers on each client box, so fewer things to break.

Bad:

- Package boundaries only hold if they are enforced. Without the CI checks in 0002, the code will drift into a tangle.
- The server and worker scale together. That is fine at one company per install.

## Alternatives considered

- One service per layer (API, business logic, database handler as separate programs). Rejected: every call becomes a network hop, deployments multiply, and we get the costs of microservices with none of the benefits at this scale.
- Microservices per business area. Rejected for the same reasons, and because nothing in a single-company install needs independent scaling.
