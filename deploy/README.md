# Deploying yyai on one box

This folder runs yyai with Docker Compose: Postgres, the migration job, the API server, the worker, and Caddy with the staff web app. Only Caddy is published. An optional Cloudflare tunnel exposes the WhatsApp webhook. The model server runs outside Docker.

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

   `POSTGRES_PASSWORD` and `MODEL_API_KEY` need real values. The four `WHATSAPP_*` lines must not be empty or the server will not start: until you set up WhatsApp, put any placeholder (for example `unset`) in them. Use only letters and digits in the password.

2. Build and start.

   ```
   docker compose -f deploy/compose.yaml up -d --build
   ```

   Compose starts Postgres, runs the migrations once, then starts the server, the worker and Caddy.

3. Check it.

   ```
   docker compose -f deploy/compose.yaml ps
   curl http://localhost:8080/api/health
   ```

   If something is not healthy, read the logs: `docker compose -f deploy/compose.yaml logs -f server worker migrate caddy`.

## Web app

Staff use the web app to read the WhatsApp chats, ask the AI questions and see the numbers. Every page needs a login with a password and a 6-digit code from an authenticator app (two-factor login).

### Create a user and set up two-factor login

1. Create the user. Choose the role: `admin` (everything), `sales` (chats, assistant, insights, approving replies) or `viewer` (chats and insights only).

   ```
   docker compose -f deploy/compose.yaml run --rm server yyai users add yasir --role admin --display-name "Yasir"
   ```

   It asks for the password twice (at least 12 characters).

2. It then prints a QR code, a setup key and a link, once. The person scans the QR code with an authenticator app on their phone (Google Authenticator, Microsoft Authenticator, 1Password or similar). If scanning is not possible, they type the setup key instead.

3. They log in with the username, the password and the 6-digit code the app shows. Arabic digits work too.

Other user commands:

```
docker compose -f deploy/compose.yaml run --rm server yyai users list
docker compose -f deploy/compose.yaml run --rm server yyai users reset yasir     # new password and new QR code
docker compose -f deploy/compose.yaml run --rm server yyai users disable yasir   # also logs them out
docker compose -f deploy/compose.yaml run --rm server yyai users enable yasir
```

Five wrong tries for one username, or 20 from one address, lock logins for 15 minutes. A session ends 12 hours after login, or after 2 hours with no use. The limits are in `auth:` in `config.yaml` (see `AuthConfig` in `apps/server/src/yyai/core/config.py`).

### Open it

- **On this machine (testing):** open <http://localhost:8080>. The defaults publish it on this machine only, over plain HTTP. Chrome, Edge and Firefox accept the login cookie on `localhost`.
- **From other office computers:** this needs HTTPS on the client's own subdomain, because the login cookie is only sent over HTTPS. See "HTTPS on the client's subdomain" below.

The header has an EN/العربية switch and a light/dark switch (it follows the device until you choose). Both are remembered in the browser.

### What each page shows

- **Chats:** every customer chat the AI is handling, newest first: name or number, the last message, the time and the channel. Search finds a name, a number or any word in the chat. Open a chat to read it as bubbles: customer, AI and staff look different, and AI replies show if they were sent. The list and the open chat refresh every few seconds. It is read-only for now: pausing the AI, taking over and quote requests come later.
- **Assistant:** chat with the same AI customers reach, with the same product table and rules. Use it to check a price, stock or how the AI answers. These chats are internal: they never show in Chats and never count in Insights. Each user has their own.
- **Insights:** numbers for today, the last 7 days, the last 30 days or this month, in three groups: leads and sales, customer demand, and busy times. The worker computes them at the top of every hour (Dubai time), so the page shows "Updated 14:00 · next 15:00". Numbers the system cannot count yet (quote requests, quotes sent, lost leads) show "Not tracked yet", never 0. "Price vs stock questions" is an estimate from keywords and says so. The after-hours share uses the working hours in `config.yaml` (`client.working_hours`), which are a placeholder until Kahraman confirms them.

### HTTPS on the client's subdomain

**PLACEHOLDER: Kahraman's subdomain and DNS provider are not known yet.** The plan (docs/decisions/0014): a subdomain such as `kahraman.<our domain>` points at the box's private LAN address, and Let's Encrypt issues its certificate through a DNS-01 challenge, so nothing on the internet needs to reach the box. When the subdomain and provider are known:

1. Build Caddy with the provider's DNS module: follow the PLACEHOLDER in `apps/web/Dockerfile`.
2. In `deploy/.env`, set `YYAI_SITE` to the subdomain, `YYAI_TLS=dns`, `YYAI_DNS_PROVIDER` and `YYAI_DNS_API_TOKEN` (a token that may only edit that one DNS zone), and `YYAI_HTTPS_BIND=443` so the office network can reach it.
3. Add a DNS A record for the subdomain with the box's LAN address.
4. `docker compose -f deploy/compose.yaml up -d --build`, then open `https://<subdomain>`.

For a quick test from another device before that, `YYAI_TLS=internal` with `YYAI_SITE=https://<box LAN address>` and `YYAI_HTTPS_BIND=<box LAN address>:8443` gives HTTPS with Caddy's own certificate. Browsers show a warning. Do not use it for real work.

## Demo data (development and demos only)

To see every page of the web app filled in, load fake chats:

```
docker compose -f deploy/compose.yaml run --rm server yyai demo seed      # 60 chats over 30 days
docker compose -f deploy/compose.yaml run --rm server yyai demo clear     # remove them again
```

- Every fake customer is named "Demo customer N", so nobody mistakes them for real ones.
- `seed` refuses to run if the database holds any real customer chat. Never use it on a live box.
- The product sheet must be loaded first: the fake replies quote prices from the product table.
- Insights is refreshed straight away.
- If you show the demo data to a client, say it is sample data.

## Try it without WhatsApp

First load the products (see "Products, prices and stock" below). Then create a user, log in to the web app and open **Assistant**. Ask a question, for example "How much is the Ethiopia Yirgacheffe 250g?" or "كم سعر قهوة كولومبيا 1 كجم؟". The worker answers in a few seconds.

The old open `webchat` test webhook is gone: it needed no login. The webhook route now accepts only channels that check a signature (WhatsApp).

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

Only Caddy is published. The server, the worker and Postgres have no ports on the host. Every API route except health, the WhatsApp webhook and login needs a staff login.
