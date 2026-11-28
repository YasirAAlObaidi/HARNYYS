"""Outbox rows can carry an image: `kind` ('text' or 'image') and `image_url`.

Existing rows stay valid: they become kind 'text'. For an image row, `text` holds the caption.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE outbox
          ADD COLUMN kind text NOT NULL DEFAULT 'text' CHECK (kind IN ('text','image')),
          ADD COLUMN image_url text;
        CREATE INDEX outbox_turn_idx ON outbox (turn_id, id);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS outbox_turn_idx; ALTER TABLE outbox DROP COLUMN IF EXISTS image_url, DROP COLUMN IF EXISTS kind")
