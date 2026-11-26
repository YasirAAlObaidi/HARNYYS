# The staff web app, built with Node and served by Caddy. The final image has no Node in it
# (docs/decisions/0017): only Caddy, the Caddyfile and the built files.
#
# Build from the repo root:  docker build -t yyai-web:dev apps/web
# deploy/compose.yaml builds it as the "caddy" service.

# --- build: install the locked dependencies, type-check and build to dist/ ----------------------------------------
FROM node:26.7.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# =====================================================================================================
# PLACEHOLDER: production HTTPS needs Caddy built with the client's DNS provider module (DNS-01, see the
# Caddyfile). The provider is not known yet. When it is, uncomment these two lines with the right module,
# and the COPY --from=caddy line further down:
#   FROM caddy:2.11.4-builder-alpine AS caddy
#   RUN xcaddy build --with github.com/caddy-dns/<provider>
# =====================================================================================================

# --- runtime: Caddy as a normal user ------------------------------------------------------------------------------
FROM caddy:2.11.4-alpine

# COPY --from=caddy /usr/bin/caddy /usr/bin/caddy

# Caddy listens on 8080 and 8443, so it needs no root and no special capability to bind a port. Removing the
# capability the official binary carries lets compose drop every capability (cap_drop: ALL).
RUN setcap -r /usr/bin/caddy \
    && addgroup -S -g 10002 web \
    && adduser -S -D -H -u 10002 -G web -h /data -s /sbin/nologin web \
    && chown -R web:web /data /config

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

USER web
EXPOSE 8080 8443
