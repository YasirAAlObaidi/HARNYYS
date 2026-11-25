# 0012. Deployment and client configuration

Status: Accepted · Date: 2026-11-22

## Context

Each client has different hardware, software and settings. The team must keep many installs updated without the core code splitting per client. Client secrets, such as ERP passwords, must not sit where every developer can read them.

## Decision

- Deploy with Docker Compose. Every client runs the same image.
- Build x86 images first. Adding ARM later is a one-line build change. The SQL Server ODBC driver is the part to check when we do.
- The model server runs outside our image, natively on Macs (see 0004).
- Client configs live in a separate private deployments repo, as `customers/<name>/config.yaml` and `compose.override.yaml`.
- Secrets are either encrypted with SOPS and age, or kept only on the client's box.
- No per-client plugins. Every handler lives in the core repo and is switched on by config.

## Consequences

Good:

- One image to test and ship. Every client gets the same fixes.
- The core repo contains no client secrets or client-specific code.
- A client's setup is readable in one folder.

Bad:

- A handler for a product only one client uses still lives in core.
- Two repos to keep in step.
- ARM clients wait until we turn that build on and test it.

## Alternatives considered

- Client folders inside the core repo. Rejected: secrets in git, and client code mixed with core.
- Per-client plugins loaded at runtime. Rejected: they break when core internals change, and they let per-client forks creep back in.
- Kubernetes. Rejected: too heavy for single-machine installs.
