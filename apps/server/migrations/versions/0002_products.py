"""Product table: the one source of prices and stock the agent may quote, loaded from the client's Excel sheet.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE products (
          code         text PRIMARY KEY,
          name_en      text NOT NULL,
          name_ar      text,
          category     text,
          description  text,
          unit         text,
          -- NULL means no price: the agent never guesses one, it hands the chat to staff.
          price        numeric(12, 2) CHECK (price >= 0),
          currency     text NOT NULL DEFAULT 'AED',
          vat_included boolean NOT NULL DEFAULT true,
          -- NULL means stock unknown: the agent says staff will confirm it.
          in_stock     boolean,
          quantity     numeric(12, 3) CHECK (quantity >= 0),
          url          text,
          image_url    text,
          attributes   jsonb NOT NULL DEFAULT '{}',
          -- Rows that disappear from the sheet are switched off, never deleted, so history keeps its names.
          active       boolean NOT NULL DEFAULT true,
          updated_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX products_active_idx ON products (active);

        CREATE TABLE product_imports (
          id           bigserial PRIMARY KEY,
          imported_at  timestamptz NOT NULL DEFAULT now(),
          source       text NOT NULL,
          imported_by  text,
          rows         int NOT NULL,
          added        int NOT NULL,
          updated      int NOT NULL,
          deactivated  int NOT NULL,
          unchanged    int NOT NULL
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_imports, products")
