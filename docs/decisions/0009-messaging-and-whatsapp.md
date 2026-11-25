# 0009. Messaging and WhatsApp

Status: Accepted · Date: 2026-11-22

## Context

WhatsApp is the main customer channel for most of our clients. WhatsApp delivers incoming messages only by webhook, meaning Meta calls a public web address. Client boxes sit inside office networks with no public address.

## Decision

- `MessagingPort` is a job separate from `CrmPort`. Messaging covers channels such as WhatsApp, email and web chat. CRM covers contacts and deals.
- WhatsApp is reached through Meta's Cloud API or a reseller such as 360dialog or Twilio. Each of these is a brand.
- Incoming webhooks reach each client box through a Cloudflare Tunnel for that client. The tunnel exposes only the webhook path. The box opens the connection outwards, so the office network needs no inbound ports.
- The outbox respects WhatsApp's 24-hour rule. Free-form replies are allowed only within 24 hours of the customer's last message. After that, only pre-approved template messages may be sent.

## Consequences

Good:

- Messages go straight from Meta, or the reseller, to the client's own box. Nothing passes through a server of ours.
- If one tunnel fails, only that client is affected.
- Changing WhatsApp provider is a config change.

Bad:

- Each install needs a Cloudflare account setup and a DNS name.
- Some client IT teams may block tunnels. We would handle that case by case.
- Template messages must be registered and approved ahead of time.

## Alternatives considered

- A hosted relay we run, which every client box calls to collect its messages. Rejected for now: it is another server we must keep up, all client messages would pass through it, and an outage would hit every client.
- Polling for messages. Rejected: WhatsApp does not support it for incoming messages.
- Treating messaging as part of the CRM. Rejected: channel and CRM are often different products.
