# Kahraman build: progress and handover

Status on 26 Nov 2026, written for Yasir, who takes over the build. Yazan made the product decisions below with Claude Code over 25–26 Nov.

> **This repo is public.** No client chats, voice notes, transcripts, phone numbers or prices quoted in chats are committed. Those stay on Yazan's laptop in git-ignored folders (`Chat samples/`, `samples/`). `deploy/.env` is git-ignored too. Keep it that way.

## 1. Where everything is

| Branch | What | State |
|---|---|---|
| `kahraman-phase-0` | Products table and Excel, search fixes, prices only from the table, quote requests and handovers, approval rules, Docker dev setup, voice test bench | Pushed. 360 tests pass. |
| `kahraman-web-app` | Staff web app: logins with 2FA, Chats, Assistant and Insights pages (built by a second Claude agent) | Backend done and pushed. Frontend status in section 4. |
| `main` | The skeleton from before | Untouched |

The approved plan (Phase 0 demo, Phase 1 production, Phase 2 operations) is summarised here. Ask Yazan for the full plan file if you need it.

### Merging the two branches
Both branches start from `244d477`. Merge `kahraman-web-app` into `kahraman-phase-0` (or both into `main`), then:
1. **Migrations.** The web app adds `0003_staff_web_app` (down_revision `0002`). Phase 0 adds `0004_quote_requests_handovers`, also with down_revision `0002` for now. **Set 0004's `down_revision` to `"0003"`** so Alembic has one head.
2. **Staff test chats.** `workflows/agent/request_tools.py` uses `INTERNAL_CHANNELS = {"staff"}` so staff test chats save no quote requests or handovers. The web branch adds `RunContext.internal`. Switch the check to `ctx.internal`, and do the same in the turn's safety net (`turn.py`, `_safety_net`).
3. **Expected conflicts** (both branches added to the same places): `core/types.py`, `core/config.py`, `bootstrap.py`, `tests/test_end_to_end.py`, `tests/conftest.py`, `deploy/clients/kahraman/config.yaml`, `pyproject.toml`, `uv.lock`. Keep both sides.
4. The web branch locks every `/api` route behind a login and closes the open webchat webhook. The Phase 0 e2e tests that call `/api/conversations` without a session need a logged-in client after the merge.
5. Run `uv run pytest -q`, `uv run lint-imports` and `uv run ruff check` in `apps/server`.

## 2. Decisions (from Yazan, binding)

- **ADRs stand as written.** Do not drop 0014 or 0017: React/Vite/TS staff web app, Caddy as the only LAN-facing service, staff logins with roles and 2FA. **0008 is unchanged:** the new tools are `write` risk with a per-tool approval rule, which Kahraman's config sets to `auto`.
- **Products live in Postgres** (single source). Excel is how the client loads products and gets data out (they are "heavy on Excel"): import products from .xlsx, and every export is .xlsx.
- **Fully local:** a local chat model and local speech-to-text, everything in Docker. Only WhatsApp traffic goes through Meta.
- **Staff alerts are WhatsApp pings only.** Supplier forwards and the monthly report still go by email.
- **Deferred:** backups, the encryption choices (backup encryption, the Cloudflare TLS path, disk encryption), and the Excel upload page in the web app ("on hold").
- **Speech-to-text: Whisper large-v3 with a product-name hint** (section 5). Jais-ASR is the backup.
- **Demo on 1 Dec 2026** (Phase 0), then the production build.

## 3. Phase 0 (demo) status

| Step | What | State |
|---|---|---|
| 1 | Review the half-finished edits from the earlier handover | Done |
| 2 | Local chat model as the default | **Open.** Needs a shortlist, Yazan's OK on 5–10 GB downloads, and a test on the real samples. The config still defaults to OpenRouter (`MODEL_*` in `.env`), and `deploy/.env` has `MODEL_NAME=not-pulled-yet`. |
| 3 | Products table with Excel import and export | Done |
| 4 | Prices and stock only from the product table | Done |
| 5 | Search: model numbers and codes win over loose matches | Done, plus fixes found with real samples |
| 6 | `create_quote_request` and `handover_to_staff` tools | Done. The staff WhatsApp ping comes later (needs the staff list and a Meta template). |
| 7 | WhatsApp test number and tunnel | **Open.** Needs Meta credentials from Yazan. |

### What was built (branch `kahraman-phase-0`)

**Products and Excel** (commit `244d477`)
- Migration `0002`: `products` (code, EN/AR names, category, unit, `price` (NULL = no price), currency, VAT, `in_stock`, quantity, attributes, `active`) and `product_imports` (log).
- Inventory brand `sql_products` (`handlers/persistence/products.py`), now Kahraman's inventory.
- `yyai products import FILE [--apply] [--by NAME] [--allow-mass-deactivation]` and `yyai products export FILE` (`cli.py`, `services/products.py`, `workflows/products.py`, `handlers/spreadsheets/xlsx.py`):
  - The import previews the changes first and changes nothing unless `--apply` is given.
  - Any bad row stops the whole import; errors are listed by row number.
  - A product missing from the sheet is switched off, never deleted.
  - A sheet that would switch off more than half the products is refused unless forced.
  - English and Arabic column headings both work, and so do Arabic digits.
  - Unknown columns become product attributes.
- Starter sheet `deploy/clients/kahraman/products.xlsx`: 190 items from the public website (109 priced).
- `scripts/setup-mac.sh` (Colima, Docker, uv) and `deploy/compose.dev.yaml` (the dev Postgres the tests use).

**Agent safety and actions** (second commit on this branch)
- **Prices only from the product table** (`workflows/agent/tools.py`):
  - The catalogue copy is used to *find* products, never for a price.
  - `search_products` returns no prices.
  - Attributes whose name looks like a price ("Trade price", "سعر…") are hidden from the model.
- **quote_price outcomes:**
  - *Clear match with a price:* the price, VAT and stock from the table. Unknown stock comes with a note telling the model not to guess.
  - *Clear match, no price:* `handover: true, handover_reason: missing_price`, and no price at all.
  - *Weak match* (score < 0.5): no price; the model asks which product.
  - *Several different products match about equally* (within 0.05, colours of one product excepted): `options` with each one's table price; the model asks which. Example: "Lebrew" matches two analysers at 1,300 and 1,400.
  - *Nothing found:* the model asks once, then hands over.
- **Search** (`services/catalogue.py`): besides 3+ digit model numbers, short codes that mix letters and digits (`F5`, `F64`, `M6`, `V60`) must appear in the product name, otherwise the score is cut. This fixed "مطاحن F5" (F5 grinders) matching a grinder cleaner. Sizes (`600gr`, `1kg`) are not codes.
- **New `write` tools** (`workflows/agent/request_tools.py`, `services/requests.py`, `handlers/persistence/requests.py`, migration `0004`):
  - `create_quote_request(code, quantity, unit?, area?, note?)`:
    - The product must be in the catalogue copy, which holds only active products.
    - Quantity must be more than 0 and at most 10,000; the area is capped at 100 characters.
    - One open request per chat and product, so a repeat call updates it; at most 10 open requests per chat.
  - `handover_to_staff(reason, summary)`: the reason is an enum, and there is one open handover per chat.
  - No argument names a customer or chat: identity comes only from `RunContext`.
- **Approval rules (0008)** (`registry.py`):
  - The default comes from the risk class: read runs automatically, everything else needs confirmation.
  - `agent.approvals` in the client config overrides it per tool. Kahraman sets both new tools to `auto`.
  - A tool that needs confirmation is not offered to the model and is refused if called. Confirming is not built yet.
  - An approval rule naming an unknown tool stops start-up.
- **Safety net** (`turn.py`): if `quote_price` said `missing_price` and the model did not call `handover_to_staff`, the turn opens the handover itself (`source = 'safety_net'`). The customer's reply still goes out.
- **Prompt** (`deploy/clients/kahraman/config.yaml`):
  - Kahraman's business is described correctly: green coffee beans and equipment, not roasted coffee.
  - Rules added for prices, unclear products, quote requests and handovers.
- `deploy/README.md` shows how to list open quote requests and handovers until the web app shows them.

## 4. Staff web app (branch `kahraman-web-app`)

Built by a second Claude agent (Opus) to Yazan's spec: backend `3d12d11`, frontend `43d886a` (WIP).

**Works at `43d886a`:**
- **Login:** password plus TOTP, with throttling.
- **Chats:** list, search and transcript, refreshed by polling.
- **Assistant:** chat with the AI on the internal staff channel.
- **Insights:**
  - Three groups, with a period switch.
  - "Updated 14:00 · next 15:00", and it refetches after the hour.
  - "Not tracked yet" cards for metrics with no data source.
- **Look and feel:**
  - Kahraman colours: gold `#BB8F44` and white from the logo, green `#1E4A23` and charcoal `#12171B` from the site.
  - Light and dark themes, checked for WCAG AA contrast.
  - EN/AR with right-to-left layout, and a bundled IBM Plex Sans Arabic font.
- **Checks:** web typecheck, lint, 98 vitest tests and `npm run build` pass. The server has 391 tests passing on that branch.

**Not done at that commit:**
- The web Dockerfile, the Caddyfile and the `caddy` service in `deploy/compose.yaml`.
- The web app section in `deploy/README.md`, `apps/web/README.md`, and Node in `setup-mac.sh`.
- No check yet in a real browser or against a running stack.

The agent was still working at handover. Newer commits may be on the branch.

**Spec from Yazan:**
- **Login:** username, password and TOTP 2FA, with roles admin, sales and viewer (ADR 0014).
- **Page 1, Chats:** every WhatsApp chat, with search and the messages styled by author (customer, AI, staff). Read-only for now. Pause and takeover come later.
- **Page 2, Assistant:** staff chat with the same AI (same tools and product table) to check prices and stock. These chats are internal: hidden from Chats and Insights, and they create no real quote requests.
- **Page 3, Insights:** leads and sales, customer demand, and busy times. A worker job takes a snapshot at the top of every hour (Asia/Dubai). Metrics with no data source yet show "Not tracked yet", never zero or invented numbers.
- **Look and feel:**
  - Kahraman's logo colours, taken from kahramandubai.com.
  - Light and dark mode.
  - An EN/AR switch with full right-to-left layout (ADR 0015).
  - No runtime calls to outside services (fonts bundled).
- **Deploy:** a Caddy image serves the built pages and proxies `/api`. Kahraman's subdomain for HTTPS (DNS-01) is still a placeholder.

**Backend on that branch:**
- `yyai users add/list/reset/disable/enable`, with argon2id passwords and server-side sessions.
- Every `/api` route needs a login except health, the signed webhooks and login/logout.
- Migration `0003`.
- `YYAI_TEST_DB_NAME` picks the test database, so two test runs do not collide.

## 5. Voice notes: model test and decision

**Method:**
- Six well-known open models were researched: GitHub stars, the Hugging Face Open ASR leaderboard, the Open Universal Arabic ASR leaderboard, and one outside test on UAE WhatsApp voice orders.
- Three were shortlisted. Two were run locally on Yazan's Mac (Apple M5, 16 GB) on 5 real Kahraman voice notes: 3 Gulf Arabic, 2 English, 8–76 s long.
- Scoring was on what the assistant needs: product, quantity, question. Word error rate needs exact reference transcripts, which we do not have.

**Result:**

| Note | Winner | Why |
|---|---|---|
| Arabic, short order (two products, two quantities) | Jais | Only Jais spelled the second product (peach, «خوخ») right; Whisper wrote a non-word |
| Arabic, 76 s, roaster asking about two origins | Whisper + hint | Only Whisper + hint got «غواتيمالا» (Guatemala) |
| Arabic, short price question per 20 kg sack | Whisper + hint | Only Whisper + hint got «نيكاراغوا» (Nicaragua); plain Whisper heard «هناك رقوة», Jais heard «rainbow» |
| English × 2 | Tie | All correct |

**Decision: Whisper large-v3, with language auto-detected and a product-name hint.**
- **Why:**
  - It caught the origin names.
  - It handles long notes in one pass.
  - It works in any language.
  - It is about 3.1 GB and fits next to the chat model on the 16 GB card.
- **Backup: Jais-ASR 4-bit (IFM).** It keeps Gulf dialect better and is about 2× faster on the Mac. But it hears only about 30 s at a time (long notes must be cut), and it has no word-list hint.
- **Not chosen:**
  - Cohere Transcribe Arabic: no language detection, weak on mixed Arabic and English, gated download.
  - Voxtral Mini Arabic: no English.
  - Audar-ASR: licence limits commercial use.
  - Qwen3-ASR: weakest on Arabic.
  - Whisper **turbo**: weaker on Arabic than large-v3.

**Lessons for building it (Phase 1.7):**
- The hint is Whisper's `prompt` / `initial_prompt`: a short list of origins, brands and model names in Arabic and English. Build it from the product table after each import, and keep it within about 200 tokens.
- Never force the language. Forcing Arabic made results worse.
- On the long note, Whisper slid into formal Arabic halfway. The meaning was kept but the wording was not, so the saved transcript is not word for word.
- Every model mangles some product names. The agent must repeat the product and quantity back before `create_quote_request`, and Kahraman's sheet should carry Arabic names as customers say them.
- WhatsApp often clips the first word of a note. That is usually a greeting, so it is harmless.

The bench is in `tools/stt-bench/` (see its README). The full report with transcripts is on Yazan's laptop only (`samples/kahraman/voice-test-results.md`).

## 6. What the real samples taught us

From Yazan's samples (chat screenshots, voice notes, text questions), kept local:
- **Kahraman is mainly a green-coffee importer.** Coffee sells in 20 kg sacks by origin, grade and screen size (for example "screen 19/20/21"). They also sell roasters (HB, Gene Café), grinders (Fiorenzato), machines (VBM) and tools (LeBrew).
- **The product data is thin.** The only product data is the public website copy. Of 72 green coffees, almost none have a price, and screen sizes are not listed. Most real questions would hand over today. **Kahraman's real price sheet is the most important missing input.**
- **Staff send PDF catalogues** (VBM, Fiorenzato). A future "send catalogue" tool would help (`send` risk, so it needs its approval rule).
- **Customers ask about** warranty, new vs used, specs, grade and sack weight. Staff answers in the chats suggest a few company facts for the prompt (warranty and maintenance in the UAE, exclusive importer of two brands, all machines new, 20 kg sacks). **Kahraman must confirm them before they go in.**
- **Tone:** Gulf dialect and warm ("يا غالي", "اخوي", "تكرم عينك"). It is a good source for the tone examples planned for `wording.yaml`.

## 7. Known issues

- **Docker image rebuild fails on this Mac** with `dns error` during `uv sync` in the build, even though containers resolve names fine. The running stack still has the image from before the second commit. The code itself passes all tests. Probably fixed by restarting Colima, or with `colima start --dns ...`.
- **Six files were already unformatted** before this work and are left as they were (`ruff format --check`): `handlers/common/http.py`, `handlers/integrations/whatsapp_cloud/handler.py`, `handlers/model/openai_compat.py`, `handlers/persistence/catalogue.py`, `handlers/persistence/conversations.py`, `services/model.py`.
- **No staff alert yet** for new quote requests and handovers. Staff see them only in the database for now, and in the web app after the merge.

## 8. Next steps, in order

1. **Local chat model (Phase 0 step 2).**
   - Shortlist 2–3 instruct models that fit in about 10 GB of graphics memory at Q4/Q5.
   - Test tool-calling in Gulf Arabic on the real text samples Yazan has locally: short price and spec questions in English and Arabic, about an HB 600 g roaster, Nicaragua by screen size, and LeBrew.
   - Yazan decides. Then make local the default in `config.yaml`: `external: false`, `allow_external: false`.
2. **WhatsApp test number and tunnel (step 7):** `docs/setup/whatsapp.html` and `deploy/README.md`.
3. **Merge the web app branch** (section 1) and fix the Docker build.
4. **From Kahraman:**
   - the price sheet (green coffee per sack, grade and screen);
   - the PDF catalogues;
   - confirmation of the company facts;
   - more voice notes;
   - staff, supplier and blocked number lists;
   - routing rules, delivery areas, follow-up schedule.
5. **Phase 1, as planned:**
   - voice notes with Whisper (1.7);
   - message echoes and takeover (1.2);
   - routing before the model (1.4);
   - price guard and frustration handover (1.5);
   - follow-ups (1.9);
   - Excel exports and the monthly lost-lead report (1.10, 1.11);
   - staff WhatsApp alerts.

## 9. Checks and commands

```
scripts/setup-mac.sh                       # Docker (Colima), dev Postgres, uv sync
cd apps/server
uv run pytest -q                           # 360 tests on kahraman-phase-0
uv run lint-imports                        # 5 layer contracts
uv run ruff check
docker compose -f deploy/compose.yaml run --rm server yyai products import /config/products.xlsx --apply --by <name>
```
