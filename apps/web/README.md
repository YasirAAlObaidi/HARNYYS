# yyai staff web app

The web app staff use in the office. It has a login and three pages:

- **Chats**: every customer chat the AI is handling. Read-only for now.
- **Assistant**: chat with the same AI to check prices, stock or answers. These chats are internal: they never show in Chats or count in Insights.
- **Insights**: numbers about leads, customer demand and busy times. The worker computes them at the top of every hour.

It is a React, Vite and TypeScript app (docs/decisions/0017). It builds to static files. In production Caddy serves them and sends `/api/*` to the yyai server. There is no Node server in production.

## Develop

Needs Node 22 or newer (`scripts/setup-mac.sh` installs it).

```
cd apps/web
npm ci
npm run dev        # http://localhost:5173, /api goes to http://127.0.0.1:8000
```

To use another API, set `YYAI_API_URL`, for example `YYAI_API_URL=http://127.0.0.1:18000 npm run dev`. You need a staff user to log in (see "Web app" in `deploy/README.md`).

## Check

```
npm run typecheck
npm run lint
npm test
npm run build      # type-checks, then writes dist/
```

## How it is put together

- `src/pages/`: the login page and the three pages.
- `src/api/`: the fetch wrapper, the response types and the TanStack Query hooks. Polling intervals are at the top of `queries.ts`.
- `src/i18n/messages.ts`: every text in English and Arabic.
- `src/styles/`: `tokens.css` (colours, type, spacing; light and dark; `tokens.test.ts` checks WCAG AA), `base.css`, `shell.css` and one file per page. Logical properties only, so Arabic mirrors.
- `DESIGN.md`: the design rules and page anatomy. Read it before changing a screen.
- `Caddyfile` and `Dockerfile`: the production image (`docker build -t yyai-web:dev apps/web`).

## Rules

- **No outside requests.** Fonts (Inter, IBM Plex Sans Arabic, Fraunces, Noto Naskh Arabic) and icons (lucide-react) are bundled. No CDN, font service or analytics. The Caddyfile's Content-Security-Policy allows only our own origin.
- **Honest numbers.** A metric the server cannot compute yet comes as `not_tracked`. The page shows "Not tracked yet", never a 0. An estimate is labelled as one.
- **Arabic first-class.** The EN/AR switch sets `<html lang dir>`. Message text uses `dir="auto"`. Inputs accept Eastern Arabic digits.
- **Pinned versions.** Every dependency has an exact version, and `package-lock.json` is committed.
- `src/test/insights-snapshot.json` is written by the server's own maths. If the snapshot format changes, regenerate it: `cd apps/server && YYAI_WRITE_WEB_FIXTURE=1 uv run pytest tests/test_insights.py -k fixture`.

## Brand

The logo is Kahraman's own, from kahramandubai.com: `src/assets/kahraman-logo-white.svg` as published, and `kahraman-logo.svg`, the same drawing with a gold mark and a wordmark that takes the text colour. The brand colours are gold `#BB8F44` and white `#FFFFFF` (the logo), and green `#1E4A23` and charcoal `#12171B` (their site). How they are used is in `DESIGN.md`.
