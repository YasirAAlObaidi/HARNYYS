# 0015. Arabic and right-to-left from day one

Status: Accepted · Date: 2026-11-22

## Context

We are launching in the UAE. Staff and customers use Arabic and English. Retrofitting right-to-left layout into a finished app means reworking every screen.

## Decision

- The React app supports right-to-left layout from the first screen.
- Inputs accept Eastern Arabic numerals.
- Brand handlers expect Arabic text stored in older `varchar` columns with Arabic collations. We have not checked how Al Ameen stores its text.
- Each model is tested on Gulf dialect before it serves a client.

## Consequences

Good:

- Arabic works properly from the start instead of being bolted on.
- Text-handling bugs from vendor databases surface early.

Bad:

- Every UI component has to be built and tested in both directions.
- Testing on dialect needs Arabic test conversations for each client.

## Alternatives considered

- English first, Arabic later. Rejected: the cost of retrofitting grows with every screen.
