# 0011. Postgres for data, jobs and vectors

Status: Accepted · Date: 2026-11-22 · Revised 2026-11-25

## Context

We need relational data, a durable job queue for agent turns and the outbox, fuzzy text search, and vector search. Every extra service on a client box is another thing to install, update and back up.

## Decision

- Use Postgres 17 with the pgvector and pg_trgm extensions for application data, embeddings and fuzzy search.
- The `turns` and `outbox` tables are themselves the work queue. The worker claims the next row with `SELECT … FOR UPDATE SKIP LOCKED`, and partial unique indexes allow at most one waiting and one running turn per conversation. Saving a message and queueing its turn happen in one transaction.
- If we later need general scheduled or ad-hoc jobs beyond turns and the outbox, we add a library such as procrastinate then, rather than writing more of our own.
- No Redis, and no separate vector database.

## Consequences

Good:

- One database to install, back up and restore per client.
- Jobs and data can change in the same transaction, which makes the outbox reliable.
- Fewer moving parts on each box.

Bad:

- Postgres carries more varied load. That is fine at the volume of one company.
- We own the small amount of claim-and-retry code for turns and the outbox, so it needs its own tests (it has them).

## Alternatives considered

- Redis with a separate queue library. Rejected: one more service per box for no gain at this scale.
- procrastinate for turns and the outbox. Rejected during the build (2026-11-25): its jobs live in its own tables, so saving a message and queueing its turn could no longer share one transaction, and the turn and outbox tables already hold all the state a queue needs.
- A dedicated vector database. Rejected: pgvector is enough for catalogue-sized data.
