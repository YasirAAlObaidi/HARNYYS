# Deploying yyai on one box

This folder runs yyai with Docker Compose: Postgres, the migration job, the API server and the worker. An optional Cloudflare tunnel exposes the WhatsApp webhook. The model server runs outside Docker.

Needs Docker with the Compose v2 plugin (`docker compose version`). On a Mac with Colima, `brew install docker-compose` adds the plugin.

```
deploy/
  compose.yaml
  .env.example          copy to .env (git-ignored) and fill in
  clients/kahraman/
    config.yaml         the client's settings
    catalogue.json      SAMPLE products, replace with the real catalogue
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

Send a message through the web chat channel, wait a few seconds for the worker to run the agent turn, then read the conversation.

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

## Catalogue

The demo catalogue is `clients/kahraman/catalogue.json`. Every item there is sample data, marked `SAMPLE-` and `(sample)`. Replace the file with the real catalogue, then load it:

```
curl -X POST http://127.0.0.1:8000/api/admin/catalogue/sync
```

The worker also syncs the catalogue when it starts and then on a timer (`worker.catalogue_sync_interval_s`, hourly by default).

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
