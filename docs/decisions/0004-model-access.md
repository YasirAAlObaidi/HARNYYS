# 0004. Model access through roles

Status: Accepted · Date: 2026-11-22

## Context

Clients will run models in very different places: the same box, another machine on the LAN, a self-hosted cloud, or a provider like Claude. Our first client has an x86 PC with a 16 GB graphics card, which limits it to small models. Small models are noticeably less reliable at calling tools correctly.

## Decision

The model always runs as a separate program outside our Docker image: vLLM, Ollama, TensorFold, MLX, llama.cpp, or a provider such as Claude. We talk to it over HTTP using the OpenAI-compatible API, plus an Anthropic adapter.

`ModelService` in the services layer:

- maps roles (`chat.default`, `chat.fast`, `embed.default`) to endpoints from the client's config, so business code never names a model;
- enforces `allow_external` for each role, false by default, so client data only goes to a cloud provider when the config says so;
- keeps capability flags for each model: tool calling, context size and languages;
- validates every tool call against the tool's schema and retries once on failure;
- caps the number of iterations in the agent loop.

Common questions such as prices use fixed, purpose-built tools rather than free improvisation, because small models handle a narrow, well-defined tool far better.

## Consequences

Good:

- Moving a model to another machine or provider is a config change.
- The same code serves a 16 GB PC and a cloud model.
- Sending data off-site is an explicit, per-role decision.

Bad:

- OpenAI-compatible servers differ in details. vLLM, for example, needs a tool-call parser setting. Each new server needs checking.
- On Macs the model server must run natively, because Docker on macOS cannot use the GPU.

## Alternatives considered

- Bundling the model server in our image. Rejected: it ties us to one GPU type and breaks on Macs.
- A third-party gateway library. Rejected for now: the interface we need is small, and owning it keeps the contract ours.
