"""Quote requests and handovers: what the agent records for staff to act on.

A quote request is a customer asking for a formal quote: the agent collects the product, quantity and area,
and staff send the quote (the agent never does). A handover is a chat that staff must answer, for example
because a product has no price. At most one of each is open per chat (per product, for quote requests), so a
repeated tool call updates the open one instead of adding another.

Revision id: 0004. It follows 0002 here; when the web app migration (0003) is merged, set down_revision to
"0003" so the chain stays straight.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE quote_requests (
          id              bigserial PRIMARY KEY,
          conversation_id bigint NOT NULL REFERENCES conversations(id),
          turn_id         bigint REFERENCES turns(id),
          code            text NOT NULL,
          product_name    text NOT NULL,
          quantity        numeric(12,3) NOT NULL CHECK (quantity > 0),
          unit            text CHECK (char_length(unit) <= 20),
          area            text CHECK (char_length(area) <= 100),
          note            text CHECK (char_length(note) <= 200),
          status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open','sent','cancelled')),
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX quote_requests_one_open
          ON quote_requests (conversation_id, code) WHERE status = 'open';
        CREATE INDEX quote_requests_status_idx ON quote_requests (status, created_at);

        CREATE TABLE handovers (
          id              bigserial PRIMARY KEY,
          conversation_id bigint NOT NULL REFERENCES conversations(id),
          turn_id         bigint REFERENCES turns(id),
          reason          text NOT NULL CHECK (reason IN
                            ('missing_price','unclear_item','asked_for_human','complaint','large_order','other')),
          summary         text CHECK (char_length(summary) <= 200),
          source          text NOT NULL CHECK (source IN ('tool','safety_net')),
          status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','closed')),
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now(),
          answered_at     timestamptz
        );
        CREATE UNIQUE INDEX handovers_one_open ON handovers (conversation_id) WHERE status = 'open';
        CREATE INDEX handovers_status_idx ON handovers (status, created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS handovers, quote_requests CASCADE")
