# Deploying yyai on one box

This folder runs yyai with Docker Compose: Postgres, the migration job, the API server and the worker. An optional Cloudflare tunnel exposes the WhatsApp webhook. The model server runs outside Docker.

Needs Docker with the Compose v2 plugin (`docker compose version`). On a Mac, `scripts/setup-mac.sh` installs and configures both through Colima.

`compose.dev.yaml` is a different file: it holds only the developer Postgres that the tests use, and it is never deployed to a client box.

```
deploy/
  compose.yaml
  .env.example          copy to .env (git-ignored) and fill in
  clients/kahraman/
    config.yaml         the client's settings
    products.xlsx       the product sheet to load (see "Products, prices and stock")
    catalogue.json      the website copy the starter sheet was made from (not read by the app)
```

## Start

Run everything from the repo root.

1. Create the secrets file and fill it in. Each line says where the value comes from.

   ```
   cp deploy/.env.example deploy/.env
   ```

   `POSTGRES_PASSWORD` and `MODEL_API_KEY` need real values for the web chat test below. The four `WHATSAPP_*` lines must not be empty or the server will not start: until you set up WhatsApp, put any placeholder (for example `unset`) in them. Use only letters and digits in the password.

2. Build and start.

   ```
   docker compose -f deploy/compose.yaml up -d --build
   ```

   Compose starts Postgres, runs the migrations once, then starts the server and the worker.

3. Check it.

   ```
   docker compose -f deploy/compose.yaml ps
   curl http://127.0.0.1:8000/api/health
   ```

   If something is not healthy, read the logs: `docker compose -f deploy/compose.yaml logs -f server worker migrate`.

## Try it without WhatsApp

First load the products (see "Products, prices and stock" below). Then send a message through the web chat channel, wait a few seconds for the worker to run the agent turn, and read the conversation.

```
curl -X POST http://127.0.0.1:8000/api/webhooks/webchat \
  -H 'content-type: application/json' \
  -d '{"user_id":"demo-1","name":"Demo","text":"How much is the Ethiopia Yirgacheffe 250g?"}'

curl http://127.0.0.1:8000/api/conversations/1/messages
```

Conversation `1` is the first one created. Messages in Arabic work the same way.

## Turn on WhatsApp

1. Fill in the four `WHATSAPP_*` values in `deploy/.env`, then restart: `docker compose -f deploy/compose.yaml up -d`.
2. Create a tunnel in the Cloudflare dashboard (Zero Trust > Networks > Tunnels), put its token in `CLOUDFLARE_TUNNEL_TOKEN`, and add one public hostname. Route only the path `/api/webhooks/whatsapp*` to `http://server:8000`. Add no other route: everything else stays private.
3. Start the tunnel:

   ```
   docker compose -f deploy/compose.yaml --profile tunnel up -d
   ```

4. In the Meta app (WhatsApp > Configuration > Webhook), set the callback URL to `https://<your-hostname>/api/webhooks/whatsapp` and the verify token to the value of `WHATSAPP_VERIFY_TOKEN`. Then subscribe to the `messages` field.

Do step 1 before step 3. With a placeholder `WHATSAPP_APP_SECRET`, the server cannot tell real Meta calls from fakes.

## Products, prices and stock

The agent quotes prices and stock only from the product table in the database. The table is loaded from the client's Excel sheet. `clients/kahraman/products.xlsx` is a starter sheet made from a copy of Kahraman's website (190 items, 81 without a price). Replace it with their own sheet when they send it.

Preview what a sheet would change. This changes nothing:

```
docker compose -f deploy/compose.yaml run --rm server yyai products import /config/products.xlsx
```

Load it:

```
docker compose -f deploy/compose.yaml run --rm server yyai products import /config/products.xlsx --apply --by <your name>
```

When the sheet loads:
- The search copy is refreshed at once.
- If any row has a problem, such as a price that is not a number, a code used twice, or "in stock" with quantity 0, the import lists every problem by row number and changes nothing.
- A product that disappears from the sheet is switched off, never deleted.
- A sheet that would switch off more than half of the products is refused unless you add `--allow-mass-deactivation`.
- An empty price cell, `0` or "price on request" all mean no price, so the agent hands the chat to staff.

To get the current table back as Excel, in the same layout so it can be edited and loaded again:

```
docker compose -f deploy/compose.yaml run --rm -v "$PWD:/out" server yyai products export /out/products-export.xlsx
```

The sheet's columns are `code`, `name_en`, `name_ar`, `category`, `unit`, `price`, `in_stock`, `quantity`, `description`, `url` and `image_url`. Common English and Arabic headings also work, for example `Item Code`, `Price (AED)`, `الرمز`, `السعر` and `الكمية`. Any other column is kept as a product detail. Details are searchable but are never used as a price. The full list is in `apps/server/src/yyai/services/products.py`.

## Quote requests and handovers

The agent never sends a formal quote. When a customer wants one, the agent records a **quote request** (product, quantity, delivery area) and tells them a colleague will send it. When only staff can answer, the agent records a **handover** and tells the customer a colleague will reply. This happens when a product has no price, the customer asks for a person, complains, or wants a large order. If a product has no price and the agent forgets to hand over, the system records the handover itself.

Both actions only write to our database. They run on their own because `agent.approvals` in `config.yaml` sets them to `auto`. Remove those lines and the agent cannot use them.

Staff alerts on WhatsApp and the web app screens come later. Until then, list what is open:

```
docker compose -f deploy/compose.yaml exec postgres psql -U yyai -d yyai -c \
  "SELECT q.id, c.external_user_id, q.product_name, q.quantity, q.unit, q.area, q.created_at
     FROM quote_requests q JOIN conversations c ON c.id = q.conversation_id WHERE q.status = 'open';"

docker compose -f deploy/compose.yaml exec postgres psql -U yyai -d yyai -c \
  "SELECT h.id, c.external_user_id, h.reason, h.summary, h.source, h.created_at
     FROM handovers h JOIN conversations c ON c.id = h.conversation_id WHERE h.status = 'open';"
```

## Changing settings

`config.yaml` is read when the server and worker start, so after editing it run:

```
docker compose -f deploy/compose.yaml restart server worker
```

To use a local model instead of the hosted one, swap the `chat.default` block in `config.yaml` for the commented llama.cpp block. The hosted block is for the demo only: do not send real client data to it until the client agrees in writing.

To serve another client, set `YYAI_CLIENT_DIR` in `deploy/.env` to that client's folder.

## Stop and reset

```
docker compose -f deploy/compose.yaml down        # stop, keep the database
docker compose -f deploy/compose.yaml down -v     # stop and DELETE the database
```

Port 8000 is bound to `127.0.0.1` and has no login yet. Do not publish it. Caddy and the web app, which will sit in front of it, come later.
