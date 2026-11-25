# 0005. Integrations: jobs, brands and helpers

Status: Accepted · Date: 2026-11-22

## Context

Every client runs a different mix of software. One client may keep stock and accounts in Al Ameen and use Zoho for CRM. Another may keep stock in Odoo. Business logic must not care which product is behind each need.

## Decision

Integrations are split into three parts.

- **Job.** A capability interface, or port, that defines what can be asked and what shape the answers take: `InventoryPort`, `AccountingPort`, `MessagingPort`, `CrmPort`, `PosPort`. A separate job exists only where a client could realistically use a different product for it.
- **Brand handler.** One folder per product, for example `handlers/al_ameen/`. A brand implements one or more jobs and does the actual communication. Al Ameen implements both inventory and accounting over one SQL connection.
- **Helper.** Shared, product-agnostic connection code at the bottom of the handlers layer, for example `handlers/common/mssql.py` and `http.py`. Only handlers import helpers.

Each client's config maps every job to exactly one brand, for example `inventory: al_ameen`. `bootstrap.py` does the wiring at startup.

We design `InventoryPort` from Al Ameen plus one other real product. We leave the accounting and POS jobs undesigned until a client needs them.

## Consequences

Good:

- Business logic never names a vendor. Switching a client's product is a config change.
- Vendor table names and API formats stay inside one brand folder.
- Mixed vendors work naturally, one brand per job.

Bad:

- A brand that fills several jobs must implement several interfaces.
- Designing a job from one product risks baking in that product's quirks, which is why we use two real products.

## Alternatives considered

- Grouping handlers by connection type, for example "database handlers" and "API handlers". Rejected: business logic grows an if/else for every vendor, and pricing code ends up knowing Al Ameen's tables.
- A single merged "database job" covering inventory and accounting. Rejected: it breaks when the two live in different products, for example accounting in a cloud product with no database we can reach.
