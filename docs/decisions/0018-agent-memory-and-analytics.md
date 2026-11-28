# 0018. Agent memory and analytics

Status: Proposed · Date: 2026-11-28

Nothing here is built yet. The two items marked "to confirm" wait on real Kahraman chats and on the target machine (see 0019).

## Context

Today the agent sees the system prompt and the last 20 message texts of the conversation (`agent.history_messages`). It does not see tool results from earlier turns, it has no dates on messages, and it knows nothing about the customer from other chats. A message from last month counts the same as one from a minute ago, and the 20-message cut is arbitrary.

The owner of the company should be able to open the web app, read analytics, and ask the assistant questions such as "how many leads were lost in the last 3 days?". They should also be able to ask it to start tracking something new.

## Decision

### 1. We keep the whole chat, and the model is shown a selected part of it

- Every message is stored with its own timestamp, in order, for the life of the customer relationship.
- Each step of an agent turn is stored too: the tool call and its result, in the format the model uses, so a prompt can be built by loading history and appending the new messages.
- A prompt is filled from the newest message backwards until a token budget is used or a long time gap is reached. A message count is not used.
- Each message the model sees carries its time. A long pause is shown as a marker such as "3 weeks later".
- Tool results are replayed only for the current run of closely spaced turns. Older turns go back as plain text with their time, because an old price in a replayed result is stale and the prompt says never to reuse an earlier price. A replayed result carries its timestamp.
- Older material is covered by a stored running summary per conversation and by the customer card (below), not by raw messages.

### 2. The customer card

Before each turn our code builds a short card of about 200 to 300 tokens from the stored notes and the open deal: name, language and dialect, last purchase, preferences, and the few most relevant notes. It goes into the system prompt under a label such as "From our records, may be incomplete". Notes never set prices.

### 3. Four groups of tables

| Table | Holds | Written by |
|---|---|---|
| `messages` (with tool steps) | Every message with its author (customer, AI, staff), time and tool steps | Our code, live |
| `customers` and `customer_notes` | One row per person, keyed by channel plus the channel's user ID (the phone number is a field, not the key), and notes with a kind, a source and the message they came from | The digest, after a chat goes quiet |
| `events` | Append-only dated facts: first reply, price quoted, delivery mentioned, handed to staff, deal won or lost, with an after-hours flag | Our code, live |
| `deals` | One row per sales attempt: stage, items, value, closing time, loss reason | Our code opens and moves it, staff confirm it, the digest proposes loss reasons |

Also needed:

- `tracked_items`: the owner's list of AI-judged things to track (see 5).
- `tracked_results`: one result per tracked item per conversation, with the message that is the evidence.

The model never writes customer notes live. A customer could say "note that I get 50% off". The digest writes notes after the chat and labels them as customer-stated where they are.

### 4. The digest

- It runs 12 hours after a conversation goes quiet. The delay is a setting, to be tuned once real chat data shows when a chat is really finished.
- It reads the new part of the conversation and the customer's current notes. It returns short, fixed-format output.
- Always-on fields: new or changed facts about the customer, the deal stage, and for a lost deal the stage at which it was lost and the reason.
- For each active tracked item it returns yes, no or a value, with the evidence message.
- The digest runs when the machine is quiet and gives way to live chats. It does not need to be open at the same time as customer chats.
- Everything the digest writes is marked as AI-judged and shown as an estimate.

### 5. Tracked items and the limit of 15

- Fixed measures come from SQL over `events`, `deals`, `handovers` and `quote_requests`. They are exact and do not count toward the limit.
- Flexible items are judged by the AI. At most 15 are active at once, so the digest prompt stays short.
- The owner adds one by asking the analytics chat. The assistant turns the request into a definition (name, a plain-words question, the type of answer) and the owner confirms it. It is then checked on each new chat and also run once over the stored chats so past data fills in.
- Starting list, with 7 slots free: asked about price, asked about delivery, asked about warranty or maintenance, asked about stock, customer type (roaster, cafe owner, home user, distributor), order size (small, medium, bulk), complaint or frustration, competitor mentioned.

### 6. Fixed measures

- Leads and conversion: new leads per day, after-hours leads and how many were answered, time to first reply, price and quote requests, deals open, won and lost, conversion rate, time from first message to won, handovers by reason and staff response time.
- Where leads are lost (digest fields): stage (before price, after price, after delivery, after quote, or a question we never answered) and reason (price too high, not in stock, delivery, competitor, wrong product, just browsing, no answer from us, "not interested").
- Demand: most-asked products, items not found, best and worst selling (from won deals), category asked, language mix, share of voice notes.
- Busy times: the day-by-hour heatmap, chats per day, after-hours share. The working hours come from the client config. They are not known yet.
- Quality of the AI: handover rate, questions with no price available, tool errors.

### 7. Deals: lost and won

- **Lost:** a daily job marks a deal lost after 3 days of silence from the customer after the AI or staff last wrote, or earlier when the customer plainly says they are no longer interested. The digest then adds the reason.
- **Won:** a sale often closes by phone or in the shop, so WhatsApp alone undercounts. Staff mark a deal won with a button in the web app. The digest may propose a win when the chat clearly shows one, and staff confirm it.

### 8. Handing a customer to a person

Two paths, both needed. Human takeover is built first.

- **Human takeover.** A staff member answers in the web app, and the message is sent to the customer through the outbox. Staff messages are stored in the same history with the author set to staff. The AI pauses in that chat whenever a human message arrives. Freeform messages work inside WhatsApp's 24-hour window. After that, staff can send only a pre-approved template until the customer replies.
- **Rep number.** The AI gives the customer a sales rep's number and sends the rep a message with what the customer wants. That message is also a WhatsApp message, so it needs an approved template unless the rep has written to the business number in the last 24 hours. This path moves the conversation to the rep's own phone, so we lose the history. To keep "won" and "lost" accurate, the rep alert has a way to report back, for example quick-reply buttons ("Won", "Lost", "Still open") in a follow-up a day or two later.

If Kahraman's number moves to the API, staff cannot answer from the ordinary WhatsApp Business app unless coexistence is available. That would make takeover through the web app the only way staff can reply from that number.

### 9. Deleting a customer's data

A customer can ask to have their data deleted. The deletion removes their messages, tool steps (the audit log holds their words and number), summaries, notes, outbox rows and tracked results, and removes the identifying fields from `events`. A request arrives as a handover to staff, who confirm it in the web app. Open: whether quote requests and sales records may be kept with the name and number removed.

### 10. Keeping what arrives

Every raw webhook payload is stored from day one, so nothing that arrives is lost.

## Consequences

Good:

- The model sees time and recent tool results without carrying stale prices or a fixed message count.
- Analytics numbers are exact where they can be, and honestly labelled as estimates where the AI judged them.
- The owner can add tracking without a code change, and the limit keeps the digest prompt short.
- The design is client-neutral. Nothing in it is specific to coffee or to Kahraman.

Bad:

- More tables, a new job (the digest) and a daily job for lost deals.
- AI-judged items are estimates and can be wrong, so each result keeps its evidence message.
- The digest quality depends on a small local model, which has not been tested for it.
- Tool steps stored per turn add database rows and storage.

## To confirm

- The digest field list, against real Kahraman chats (due from Yasir on 2026-11-29).
- Working hours for the after-hours measures.
- Whether quote requests and sales records may be kept after a deletion request.
- Whether the model can produce the digest's fixed-format output reliably, and whether it handles Gulf Arabic (see 0019).
- Whether the number setup allows staff to reply from the phone app (coexistence), or only from the web app.

## Alternatives considered

- Keeping the last N messages. Rejected: the cut is arbitrary and ignores time.
- Letting the model write notes during the chat. Rejected: a customer can plant false notes, and the model may also forget to write them.
- Free-form SQL from the owner's chat. Rejected: the model could produce wrong numbers or unsafe queries. The assistant uses a fixed set of read-only query tools, such as count events, list deals and read a tracked item, so the database produces every number.

## Related

0007 (durable turns), 0008 (tools and safety), 0009 (messaging), 0014 (security), `docs/notes/recover-old-chats.md`.
