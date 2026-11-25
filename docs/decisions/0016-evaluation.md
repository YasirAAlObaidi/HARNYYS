# 0016. Evaluation with replay tests

Status: Accepted · Date: 2026-11-22

## Context

Swapping a model or editing a prompt can quietly break answers, such as wrong prices or broken tool calls. Clients expect the system to work immediately, so we cannot rely on staff catching mistakes.

## Decision

- For each client, keep a replay test set of real conversations, with the responses each handler returned recorded at the time.
- Run it on every model or prompt change, and before each release to that client.
- Staff approval of replies is a per-project switch (see 0008), not a requirement for going live.

## Consequences

Good:

- Regressions show up in our tests, not in a customer's chat.
- Model swaps become measurable, not guesswork.

Bad:

- The test sets need curating and must respect each client's data retention rules.
- Recorded handler responses go stale as client data changes.

## Alternatives considered

- Mandatory staff approval before go-live. Rejected as unrealistic for clients.
- Manual spot checks. Rejected as unreliable and unrepeatable.
