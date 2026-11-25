# 0006. Our database vs vendor databases

Status: Accepted · Date: 2026-11-22

## Context

We keep our own data in Postgres. We also need to reach vendor databases such as Al Ameen's SQL Server. We own our schema. We do not own the vendor's schema, and it can change whenever the vendor ships an update. Some projects also need to write to the vendor database, for example an inventory manager importing a stock sheet.

## Decision

- **Our database.** We own the Postgres schema and manage it with SQLAlchemy 2 and Alembic migrations. Only the persistence handler touches it.
- **Vendor databases.** We reach them only through brand handlers.
  - Reads use a least-privilege login limited to the tables or views we need, with query timeouts.
  - At startup, a schema check fails loudly if the vendor has changed those tables.
- **Writes to vendor databases.** Allowed per project, but never through SQL the model writes. Writes go only through purpose-built, tested write tools, such as a stock import, that:
  - validate every row;
  - show a preview of the change;
  - back up the affected rows;
  - write everything in one transaction, or nothing;
  - record who did it in the audit log.
- **The vendor's own import feature.** Prefer it where one exists, because it runs the vendor's own checks. We have not checked whether Al Ameen has one.
- **Permission.** Before connecting directly to a vendor database, get the client's written permission and check the vendor's licence terms.

## Consequences

Good:

- Our schema evolves safely. Vendor data is reached in controlled, testable ways.
- Vendor updates that break our queries are caught at startup, not mid-conversation.
- Writes are possible where a project needs them, without handing the model raw SQL.

Bad:

- Each write tool is custom work per product.
- Writing directly to vendor tables can skip the vendor's own posting logic. Each write tool must be checked against how the product expects data to change.

## Alternatives considered

- One handler for both our database and vendor databases. Rejected: it blurs ownership, transactions and failure modes.
- A hard ban on vendor writes. Rejected: real projects need it.
- Letting the model write SQL. Rejected as unsafe.
