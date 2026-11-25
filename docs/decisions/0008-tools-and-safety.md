# 0008. Tools, risk classes and RunContext

Status: Accepted · Date: 2026-11-22

## Context

If tools map straight onto service methods, the model chooses every argument, including whose data to read. A customer who writes "what's the balance on account 1042?" could lead the model to pass `customer_id=1042` and leak another customer's data. Different projects also need different amounts of human approval.

## Decision

Each tool has:

- its own pydantic schema, written for the model;
- a risk class: read, draft, write or send;
- an approval rule;
- a timeout;
- a cap on the size of its result.

`RunContext` holds the customer, the staff user and their role, the channel, and the project's rules. Our code sets it. The model never supplies any of it as an argument. Tools read identity and scope only from `RunContext`.

Approval rules are switched on or off per project, never forced. A sensible default:

- read tools run automatically;
- customer replies send automatically;
- writes to the ERP show a preview, and the staff member who asked for them confirms it.

## Consequences

Good:

- The model cannot widen its own access by choosing arguments.
- Each project gets the level of approval that fits how the client actually works.
- Every tool's risk is explicit and visible in the code.

Bad:

- Each tool needs more than a function signature, so there is more upfront work per tool.
- Weak approval settings are possible, so project setup must choose them deliberately.

## Alternatives considered

- Exposing service methods directly as tools. Rejected for the scope problem above.
- Mandatory staff approval of every reply. Rejected: clients expect the system to work immediately and will not sit approving messages.
