# 0007. Agent turns run durably in the worker

Status: Accepted · Date: 2026-11-22

## Context

A local model can take a minute to answer. If the agent runs inside a webhook request, the sender times out and retries, so the customer gets two replies. If the process restarts mid-answer, the customer gets none. Two quick messages can also produce replies that cross.

## Decision

- Webhook requests save the message and return immediately.
- Inbound messages are stored keyed by their source message ID, so duplicates are dropped.
- Agent turns run only in the worker.
- Each turn is a stored record that moves through these states: received, running, awaiting_confirmation, sending, then sent or failed.
- A lock per conversation lets only one turn run at a time in each conversation.
- Outgoing messages go into an outbox table and are retried until delivered.

## Consequences

Good:

- No duplicate or lost replies after timeouts, retries or restarts.
- Every turn's state is visible to staff and to us.
- Delivery problems are retried automatically and are easy to diagnose.

Bad:

- More tables and states to build and test before the first reply goes out.
- Replies arrive slightly later than an in-request answer would, because the job is queued first.

## Alternatives considered

- Running the agent inside the request. Rejected: it fails under slow models, retries and restarts.
- Redis or another external queue. Rejected: Postgres already gives us a durable queue (see 0011).
