# Design: Kahraman staff app

The colours are Kahraman's. The quality bar is the best work tools (Linear, Front, Stripe, ChatGPT). The app is calm, warm and precise: content leads, chrome recedes. Read this before changing a screen.

## Mood

- **Amber light, not bling.** *Kahraman* means amber. Gold is a thin line, one indicator or the logo mark. It is never a fill, a gradient or a button.
- **Green is the house.** Deep green carries the navigation rail and the one main action on a screen.
- **Paper and espresso.** Light mode is warm paper, never pure white. Dark mode is the brand charcoal, never pure black.
- **Editorial calm.** A serif for titles and big numbers, a precise sans for everything else. Few lines, generous space.
- **Honest data.** A number we do not measure says "Not tracked yet", never 0.

## Tokens

All tokens are in `src/styles/tokens.css`: light (default), dark (`<html data-theme="dark">`), and a copy of dark for the device setting. `src/styles/tokens.test.ts` checks every text pair at 4.5:1 and every control edge, focus ring and chart mark at 3:1, in both themes. Change a colour, run `npm test`.

| Role | Light | Dark | Use |
|---|---|---|---|
| `--bg-canvas` | `#F5F1EA` | `#12171B` | page |
| `--bg-surface` | `#FBF9F5` | `#181D21` | cards, list, panes |
| `--bg-raised` | `#FFFFFF` | `#1F2428` | inputs, menus |
| `--bg-sunken` | `#EFEAE1` | `#0D1114` | chat canvas, wells, empty heatmap cells |
| `--bg-selected` | `#E6EDE3` | `#1C3322` | selected row |
| `--text-primary` / `secondary` / `muted` | `#12171B` / `#4F4B45` / `#6B655D` | `#F2EDE4` / `#C3BBAE` / `#9A9286` | three text tones only |
| `--action-primary-bg` | `#1E4A23` | `#357A3E` | the one primary button (dark mode lifts the green: brand green vanishes on charcoal) |
| `--nav-bg` | `#1E4A23` | `#0F1813` | navigation rail |
| `--accent-gold` | `#BB8F44` | `#BB8F44` | decoration only on light (2.95:1 on white) |
| `--accent-gold-ink` | `#7D5E24` | `#D1AA66` | gold as text or icon |
| `--bubble-in` / `out` / `note` | white / green tint / amber tint | | customer / staff / AI |
| `--chart-1` / `2` / `3` | green / slate blue / gold | lifted for dark | series, in this order, never cycled |
| `--heat-0` … `--heat-7` | pale to bronze | charcoal to glowing amber | heatmap (0 = no messages, untinted) |

**Brand colours:** gold `#BB8F44` and white `#FFFFFF` from the logo; green `#1E4A23` and charcoal `#12171B` from kahramandubai.com.

**Type:** Inter (Latin UI), IBM Plex Sans Arabic (Arabic UI), Fraunces (display: page titles, login and empty-state headlines, KPI values), Noto Naskh Arabic (Arabic display). All bundled from `@fontsource`; nothing is fetched at runtime. Weights 400, 500 and 600 only. Arabic is about 1px larger with more line height (`:lang(ar)` in tokens.css), and never gets letter-spacing or italics. Numbers use Western digits in both languages; inputs accept Eastern Arabic digits.

**Space and shape:** a 4px scale. Radii 4 (chips, heatmap cells), 8 (buttons, inputs), 12 (cards), 16 (bubbles, with a 4px tail corner on the speaker's side), 24 (login panel, composer). Cards are flat with a 1px border; only floating things (menus, the phone account sheet) get a shadow.

**Icons:** `lucide-react`, 16-18px, stroke 1.5. Arrows, chevrons and send get `className="icon-directional"` so they flip in Arabic. Clocks, ticks, the mic and logos never flip.

**Motion:** 80-200ms, decelerating. Rows and messages rise 4px as they appear; the period thumb slides. No count-ups, no chart draw-in on refresh. `prefers-reduced-motion` turns it off.

## Gold and green rules

- At most one or two gold touches per screen: the logo mark, the 3px active-nav bar, the hairline under the login title, the AI sparkle, the focus ring, the heatmap.
- Gold text on light surfaces always uses `--accent-gold-ink`.
- Exactly one green primary button per view. Everything else is secondary or ghost.
- Never: gold fills or gradients, pure white or black pages, gold next to green in a chart, colour as the only signal.

## Layout

- **Shell** (`src/styles/shell.css`): a green rail at the inline start (right in Arabic), no top bar. 232px with labels at 1280px and up; a 64px icon rail from 768px; below 768px a bottom tab bar (Chats, Assistant, Insights, Account), hidden inside an open chat.
- **Page header:** 56px, title (display face) at the start, controls at the end.
- **Login:** a 400px panel on paper with a faint gold lattice. Two steps in one card: username and password, then the 6-digit code as six cells (one real input; paste and Eastern Arabic digits work; six digits sign in by themselves). Errors never say which part was wrong; a lockout shows a live countdown.
- **Chats:** list 360px, then the conversation. 72px rows with a tinted avatar, name, time, and the last message ("AI:" prefix). Rows grouped Today / Yesterday / Earlier. `/` focuses search. The conversation sits on the sunken canvas in a 760px column: customer bubbles at the start, AI (amber, "Kahraman AI" with a sparkle) and staff (green) at the end, day separators, and a read-only footer. Later status chips go in `chat-row__chips` and actions in the `transcript__actions` toolbar.
- **Assistant:** one 720px column. Staff questions are green bubbles at the end; answers are plain prose beside a gold sparkle mark, with a Copy button. Empty state: a display-face greeting, the composer, four suggestions (one in the other language). The composer is a 24px-radius box that grows to 8 lines; Enter sends.
- **Insights:** 12-column grid in three sections, each with a heading and one line of description. KPI cards show a display-face value and the change against the previous period (arrow, sign, %, coloured by whether up is good; grey within ±2%). The change is only shown when stored data reaches back that far. Ranked lists put a soft gold bar behind each label. The heatmap is a 7-step amber scale with a dashed frame over working hours, and turns to 24 × 7 on a phone. The freshness line turns amber after 65 minutes and red after 3 hours.

## Arabic and right to left

- Logical CSS only (`inline`/`block`, `start`/`end`). Never `left`/`right`.
- Messages, previews and product names get `dir="auto"` and a `lang` from their letters, so they read correctly inside either UI language.
- Names in headings use `<bdi>`; phone numbers use `<bdi dir="ltr">`; username, password and code inputs stay left to right.
- Charts reverse their time axis in Arabic, so time runs right to left.
- Anything visually hidden must stay inside its container (`.visually-hidden` is pinned to the corner, and wide hidden things sit in a hidden wrapper). Otherwise it can push the page sideways in Arabic.

## Checking a change

1. `npm run typecheck && npm run lint && npm test && npm run build`.
2. Look at it in light and dark, English and Arabic, at 1440px and 390px. Nothing may scroll sideways.
