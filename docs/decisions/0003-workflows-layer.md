# 0003. Workflows layer and the agent loop

Status: Accepted · Date: 2026-11-22

## Context

The agent does not fit neatly under the business services. It sits among them and drives them. Our first sketch put the agent beside the other services, but then services call each other in loops: the conversation service calls the agent, the agent's tools call the CRM and conversation services, and those may call back. import-linter's layers contract does not catch calls inside one layer. The blind review flagged this.

## Decision

Add a Workflows layer between Entry and Services. It holds:

- use cases: handling an inbound message, running an agent turn, delivering the outbox, handling confirmations;
- the agent loop, its tool registry and its tools.

Workflows compose services. Services never call each other and never call upward. Each tool is a small, fixed piece of workflow code. It may call more than one service in a set order: `quote_price`, for example, finds the item in the catalogue service, then asks the pricing service for the live price (see 0008 and 0010).

The agent reaches the model through `ModelService` in the services layer, never through the model handler directly. That keeps the no-skipping rule intact.

## Consequences

Good:

- No call cycles. Dependencies point one way only.
- The agent and the use cases sit where they actually belong: above business logic, driving it.
- Services stay small and testable on their own.

Bad:

- One more layer, so more pass-through code for simple paths.
- Logic that combines two services must live in a workflow, even when it feels small. That is the point, but it takes discipline.

## Alternatives considered

- The agent as a service beside the other services. Rejected because of the call cycles described above.
- The agent calling handlers directly. Rejected: it would bypass business rules and break the layering.
