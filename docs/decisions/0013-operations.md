# 0013. Operations across client sites

Status: Accepted · Date: 2026-11-22

## Context

We will run many installs on hardware we do not control, inside networks we cannot normally reach. Without a plan, versions drift, backups go untested, and failures are found by clients.

## Decision

These are in place before the second install:

- A fleet manifest listing each client's version, model and hardware.
- Pinned updates that each box pulls, with a way to roll back.
- An automatic `pg_dump` before every migration.
- Nightly encrypted backups kept off the box, with restores tested.
- An outbound-only heartbeat that carries no client data.
- Remote support through our own Tailscale tailnet, with the client's written consent.
- The model server supervised by systemd or launchd, with health checks.

## Consequences

Good:

- We know what runs where, and we hear about problems before clients do.
- Failed updates and data loss can be recovered from.
- Remote support needs no inbound ports.

Bad:

- Real work before the second client, which delays it.
- Restore tests and the manifest need routine care.

## Alternatives considered

- Handling operations case by case. Rejected: it does not scale past a few installs.
- Full remote monitoring that collects client data. Rejected for privacy reasons. The heartbeat stays content-free.
