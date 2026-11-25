# 0014. Security baseline

Status: Accepted · Date: 2026-11-22

## Context

Each box holds credentials for the client's ERP and messaging accounts, plus customer conversations. Office networks are not a security boundary: guest Wi-Fi often shares the same network. The UAE data-protection law, Federal Decree-Law 45 of 2021, applies to the personal data we handle.

## Decision

- Only Caddy is exposed on the LAN. Postgres and the other services stay internal.
- Disks are encrypted.
- Containers run as non-root users.
- Staff log in with roles and multi-factor authentication.
- HTTPS uses a per-client subdomain with a Let's Encrypt certificate issued through DNS (DNS-01), pointing at the box's private IP. This avoids installing a root certificate on every device.
- Every agent action goes into an audit log.
- Each client gets set data retention periods, in line with the UAE data-protection law.

## Consequences

Good:

- A stolen disk or a guest on the Wi-Fi does not expose ERP credentials.
- Staff get trusted HTTPS with no certificate warnings.
- We can show exactly what the agent did, and when.

Bad:

- DNS setup is needed for each client.
- Multi-factor login adds friction for staff.
- Retention rules need agreeing with each client.

## Alternatives considered

- Plain HTTP on the LAN. Rejected: credentials would travel in the clear.
- Caddy's internal certificate authority. Rejected: every device needs a root certificate installed.
- Trusting the office network. Rejected for the reasons above.
