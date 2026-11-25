"""Initial schema: conversations, messages, turns, outbox, audit log, catalogue copy.

Revision ID: 0001
Revises:
Create Date: 2026-11-25
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE TABLE conversations (
          id               bigserial PRIMARY KEY,
          channel          text NOT NULL,
          external_user_id text NOT NULL,
          customer_name    text,
          last_inbound_at  timestamptz,
          created_at       timestamptz NOT NULL DEFAULT now(),
          UNIQUE (channel, external_user_id)
        );

        CREATE TABLE turns (
          id              bigserial PRIMARY KEY,
          conversation_id bigint NOT NULL REFERENCES conversations(id),
          state           text NOT NULL CHECK (state IN
                            ('received','running','awaiting_confirmation','sending','sent','done','failed')),
          attempts        int NOT NULL DEFAULT 0,
          steps           int NOT NULL DEFAULT 0,
          error           text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          started_at      timestamptz,
          finished_at     timestamptz
        );
        -- At most one waiting and one running turn per conversation: this is the per-conversation lock.
        CREATE UNIQUE INDEX turns_one_waiting ON turns (conversation_id) WHERE state = 'received';
        CREATE UNIQUE INDEX turns_one_running ON turns (conversation_id) WHERE state = 'running';
        CREATE INDEX turns_state_idx ON turns (state, id);

        CREATE TABLE messages (
          id              bigserial PRIMARY KEY,
          conversation_id bigint NOT NULL REFERENCES conversations(id),
          direction       text NOT NULL CHECK (direction IN ('in','out')),
          source_id       text,
          text            text NOT NULL,
          media           jsonb NOT NULL DEFAULT '[]',
          turn_id         bigint REFERENCES turns(id),
          created_at      timestamptz NOT NULL DEFAULT now()
        );
        -- A provider message ID is stored once, so redelivered webhooks are ignored.
        CREATE UNIQUE INDEX messages_source_uq ON messages (conversation_id, source_id) WHERE source_id IS NOT NULL;
        CREATE INDEX messages_conversation_idx ON messages (conversation_id, id);

        CREATE TABLE outbox (
          id                  bigserial PRIMARY KEY,
          conversation_id     bigint NOT NULL REFERENCES conversations(id),
          turn_id             bigint REFERENCES turns(id),
          message_id          bigint REFERENCES messages(id),
          text                text NOT NULL,
          status              text NOT NULL CHECK (status IN ('awaiting_approval','pending','sending','sent','failed')),
          attempts            int NOT NULL DEFAULT 0,
          next_attempt_at     timestamptz NOT NULL DEFAULT now(),
          claimed_at          timestamptz,
          provider_message_id text,
          last_error          text,
          created_at          timestamptz NOT NULL DEFAULT now(),
          sent_at             timestamptz
        );
        CREATE INDEX outbox_due_idx ON outbox (status, next_attempt_at);

        CREATE TABLE audit_log (
          id         bigserial PRIMARY KEY,
          turn_id    bigint REFERENCES turns(id),
          kind       text NOT NULL,
          name       text,
          data       jsonb NOT NULL DEFAULT '{}',
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX audit_turn_idx ON audit_log (turn_id);

        CREATE TABLE catalogue_items (
          code         text PRIMARY KEY,
          name_en      text NOT NULL,
          name_ar      text,
          category     text,
          description  text,
          price        numeric(12,2),
          currency     text NOT NULL,
          vat_included boolean NOT NULL DEFAULT true,
          url          text,
          image_url    text,
          attributes   jsonb NOT NULL DEFAULT '{}',
          search_text  text NOT NULL,
          synced_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX catalogue_search_trgm ON catalogue_items USING gin (search_text gin_trgm_ops);
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS catalogue_items, audit_log, outbox, messages, turns, conversations CASCADE"
    )
