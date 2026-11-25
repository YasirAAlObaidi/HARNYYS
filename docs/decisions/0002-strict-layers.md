# 0002. Strict layers, no skipping

Status: Accepted · Date: 2026-11-22

## Context

We want each layer to have one job and to be replaceable. If any layer may call any other, the business logic ends up knowing about vendor databases and HTTP details, and changes ripple everywhere.

## Decision

The layers, top to bottom:

1. Frontend: the web app in the browser.
2. Entry: API routes and worker jobs.
3. Workflows: use cases and the agent loop (see 0003).
4. Services: business logic.
5. Handlers: our database, the model, and brand handlers for client software (see 0005).
6. Outside programs: Postgres, model servers, vendor systems.

A layer calls only the layer directly below it. Skipping a layer is forbidden.

Two exceptions:

- `core` holds config, logging, errors and shared data types. Every layer may import it, and it imports nothing from any layer.
- `bootstrap.py` is the composition root. It reads the client config, builds the brand handlers, binds them to jobs and builds the tool registry. It is the only module allowed to import every layer, and only `main.py` and `worker.py` call it.

The rules are enforced in CI with import-linter:

- a layers contract for the order;
- forbidden contracts for every pair of layers that are not neighbours, so skipping fails the build;
- an independence contract so services do not import each other.

## Consequences

Good:

- Each layer can be read, tested and replaced on its own.
- Vendor and model details cannot leak into business logic.
- Violations fail the build instead of surfacing in review.

Bad:

- Simple reads need pass-through methods, for example a service method that only calls a handler. We accept this cost.
- Without `core`, every layer would redefine the same types, so `core` must stay small and free of logic.

## Alternatives considered

- Layers that may skip downwards. Rejected: within months the API would call handlers directly and the services layer would stop meaning anything.
- No enforcement, relying on review. Rejected: rules nobody checks get broken.
