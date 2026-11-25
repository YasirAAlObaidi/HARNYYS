# Handover (2026-11-25)

Goal: a Kahraman demo on the real architecture, due **1 Dec 2026**. Customers ask about coffee and machines on WhatsApp.

## State
- Docs: `docs/index.html` (architecture), `docs/flows/` (animations), `docs/decisions/` (17 decision records), `docs/setup/whatsapp.html` (Meta setup, step by step).
- Server: `apps/server`. Strict layers enforced by import-linter. 246 tests. Run `uv run pytest -q` and `uv run lint-imports`.
- Deploy: `deploy/compose.yaml`, `deploy/README.md`, demo client in `deploy/clients/kahraman/`. The catalogue there has 190 real items from kahramandubai.com. Arabic names are our own translations, and 81 items have no price ("price on request").
- Model is switchable through `deploy/.env`: `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_EXTERNAL`, `MODEL_ALLOW_EXTERNAL`. For local testing, run Ling-3.0-tiny with `~/llama-ling/serve.sh --alias ling-3.0-tiny --chat-template-kwargs '{"enable_thinking":false}'` on port 8080. The target is Qwen3.8-27B on OpenRouter (`qwen/qwen3.8-27b`).

## Unfinished / unverified
1. The last commit includes **unreviewed, possibly half-finished edits** to `services/model.py` and `workflows/agent/tools.py`. An agent was stopped mid-debug while working on why Ling's tool calls fail validation. Review them and re-run the tests.
2. No end-to-end conversation has been confirmed with a real model. Ling skipped the tool on one Arabic test prompt but called it correctly in English.
3. Search ranks model numbers loosely: "CBR 101" returns the CBR-1200 first. Fix the ranking in `services/catalogue.py`.
4. WhatsApp is not connected yet. Follow `docs/setup/whatsapp.html`. The test number reaches at most 5 verified phones.
5. Not built: the staff web UI, logins on the admin routes, write tools (stock import), speech.
6. `docker compose` needs `brew install docker-compose` and the plugin config. See the setup guide.

## Rules for whoever continues
- Read `HANDOVER.md`, then `docs/index.html`.
- Sonnet agents do the building. The main session coordinates.
- Never commit `deploy/.env`.
