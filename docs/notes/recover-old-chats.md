# Note: recover the old chats (secondary task, important)

Status: idea, not started. Written 2026-11-28 from a planning talk with Yasir.

## Why

Kahraman's existing WhatsApp chats hold what the memory and analytics need: who the customers are, what they bought, what they asked, where leads were lost. Without them every customer starts empty.

## What we know

- The WhatsApp Cloud API has **no endpoint to fetch past messages**. We only see messages that arrive after our webhook is live.
- The one official route is **coexistence**: it can send about 6 months of one-to-one chat text once, at onboarding, through the `history` webhook. Meta documents it for Solution Partners and Tech Providers. Whether a direct developer can use it, and whether the UAE is supported, is unverified. Next step is to ask Meta support (topic "WABiz: Onboarding", request type "Embedded Signup - Coexistence Onboarding").
- The pull window is 24 hours after onboarding and can't be repeated without offboarding.

## Fallback: our own capture tool

If Meta gives us nothing, build a small tool that opens each chat in the WhatsApp Business app or WhatsApp Web one by one, scrolls to the top, takes screenshots, and reads the text out of the images (OCR or a vision model).

Things to settle before building:

- **Permission.** The client must agree, and so should the people in the chats. Check the UAE data-protection rules before we store old customers' messages.
- **Which surface.** WhatsApp Web is easiest to automate. It needs the client's phone to link a device, and it must not break their number (automation can get a number flagged, so test on a spare number first).
- **Quality.** Capture the sender side (customer or staff), the time and the date separators, not only the words. Arabic and mixed Arabic and English text must be checked against a sample.
- **Media.** Voice notes and images need their own handling (speech-to-text for voice notes).
- **Format.** Import into the same `messages` table as live chats, marked as imported, with the original timestamps. Imported rows are never mixed up with live ones.
- **Alternative.** The in-app "Export chat" button makes a text file per chat. It is slower to do by hand but needs no OCR. An importer for those files is simple and could be the first thing we build.

## Order of work

1. Ask Meta about coexistence (free, quick).
2. Build the importer for exported chat text files.
3. Only if needed, build the screenshot tool.
