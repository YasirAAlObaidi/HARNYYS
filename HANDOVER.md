# Handover (2026-11-25)

Goal: a Kahraman demo on the real architecture, due **1 Dec 2026**. Customers ask about coffee and machines on WhatsApp.

## State
- Docs: `docs/index.html` (architecture), `docs/flows/` (animations), `docs/decisions/` (17 decision records), `docs/setup/whatsapp.html` (Meta setup, step by step).
- Server: `apps/server`. Strict layers enforced by import-linter. 246 tests. Run `uv run pytest -q` and `uv run lint-imports`.
- Deploy: `deploy/compose.yaml`, `deploy/README.md`, demo client in `deploy/clients/kahraman/`. The catalogue there has 190 real items from kahramandubai.com. Arabic names are our own translations, and 81 items have no price ("price on request").
- Model is switchable through `deploy/.env`: `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_EXTERNAL`, `MODEL_ALLOW_EXTERNAL`. For local testing, run Ling-3.0-tiny with `~/llama-ling/serve.sh --alias ling-3.0-tiny --chat-template-kwargs '{"enable_thinking":false}'` on port 8080. The target is Qwen3.8-27B on OpenRouter (`qwen/qwen3.8-27b`).

## WhatsApp status (2026-11-25)
Working end to end on Meta's test number with the quick tunnel. Two things were not in the first version of the guide and cost an hour:
- The Meta app must be **Published (Live)**, or Meta only sends the dashboard "Test" webhook, never real messages.
- The test WhatsApp account must have our app **subscribed**: `POST /{WABA_ID}/subscribed_apps` with the access token (done for WABA 2174242160199038). Check with `GET /{WABA_ID}/subscribed_apps`; our app must be listed.
The quick tunnel URL changes on every restart; re-enter it in Meta each time. The access token in `deploy/.env` is temporary (hours): replace it with a system-user token before the demo.

## Unfinished / unverified
1. The last commit includes **unreviewed, possibly half-finished edits** to `services/model.py` and `workflows/agent/tools.py`. An agent was stopped mid-debug while working on why Ling's tool calls fail validation. Review them and re-run the tests.
2. First real WhatsApp conversation works with Ling: it searched the catalogue, quoted live prices and replied on WhatsApp. Arabic and Gulf-dialect quality still unchecked; Ling skipped the tool on one Arabic test prompt earlier.
3. Search ranks model numbers loosely: "CBR 101" returns the CBR-1200 first. Fix the ranking in `services/catalogue.py`.
4. WhatsApp runs on the test number (max 5 verified phones). Before the demo: system-user token, named tunnel on our own domain, business verification in parallel.
5. Not built: the staff web UI, logins on the admin routes, write tools (stock import), speech.
6. `docker compose` needs `brew install docker-compose` and the plugin config. See the setup guide.

## Rules for whoever continues
- Read `HANDOVER.md`, then `docs/index.html`.
- Sonnet agents do the building. The main session coordinates.
- Never commit `deploy/.env`.
