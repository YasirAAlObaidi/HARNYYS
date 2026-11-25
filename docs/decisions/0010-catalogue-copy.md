# 0010. Catalogue copy for product matching

Status: Accepted · Date: 2026-11-22

## Context

Customers ask for products in free text, often in Arabic, sometimes misspelt: "20L bottle". The ERP needs an exact item code. Matching words to codes is the real problem in a price request, and doing it against the vendor database on every request is slow and fragile.

## Decision

- On a schedule, copy the item catalogue from the ERP into Postgres: item codes, Arabic and English names, and units.
- Match the customer's words against this copy using pg_trgm for fuzzy text matching and pgvector for similarity search.
- Then fetch the live price from the ERP using the exact code.
- The ERP stays the source of truth for prices, VAT and per-customer price levels. We never compute a price that the ERP should provide.

## Consequences

Good:

- Matching is fast and copes with Arabic, English and typos.
- Live prices still come from the ERP, so quotes stay correct.
- The vendor database sees fewer, simpler queries.

Bad:

- The copy can be out of date between syncs. A new item may not match until the next sync.
- Sync jobs need monitoring per client.

## Alternatives considered

- Searching the vendor database directly with LIKE queries. Rejected: slow, weak on Arabic and typos, and heavy on the vendor system.
- Letting the model guess item codes. Rejected as unreliable, especially with small models.
