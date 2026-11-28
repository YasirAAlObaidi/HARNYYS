"""Staff web app: logins with 2FA, sessions, login throttling, internal chats and hourly insight snapshots.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Internal chats (the staff Assistant page) never show on the Chats page and never count in Insights.
        ALTER TABLE conversations ADD COLUMN internal boolean NOT NULL DEFAULT false;
        -- The old web chat channel was only ever used for curl tests, so its chats are test chats.
        UPDATE conversations SET internal = true WHERE channel IN ('webchat', 'staff');
        CREATE INDEX conversations_customer_recent_idx
          ON conversations ((COALESCE(last_inbound_at, created_at)) DESC) WHERE NOT internal;
        CREATE INDEX messages_created_idx ON messages (created_at);
        CREATE INDEX audit_created_idx ON audit_log (created_at);

        CREATE TABLE staff_users (
          id             bigserial PRIMARY KEY,
          username       text NOT NULL CHECK (username = lower(username) AND username <> ''),
          display_name   text,
          role           text NOT NULL CHECK (role IN ('admin', 'sales', 'viewer')),
          password_hash  text NOT NULL,   -- argon2id
          totp_secret    text NOT NULL,   -- base32, for the authenticator app
          -- The last 30-second TOTP step accepted, so the same code can never be used twice.
          totp_last_step bigint,
          active         boolean NOT NULL DEFAULT true,
          created_at     timestamptz NOT NULL DEFAULT now(),
          last_login_at  timestamptz
        );
        CREATE UNIQUE INDEX staff_users_username_uq ON staff_users (username);

        CREATE TABLE staff_sessions (
          -- SHA-256 of the cookie value. The cookie itself is never stored, so a copy of the database
          -- cannot be used to log in.
          token_hash   text PRIMARY KEY,
          user_id      bigint NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
          created_at   timestamptz NOT NULL DEFAULT now(),
          last_seen_at timestamptz NOT NULL DEFAULT now(),
          expires_at   timestamptz NOT NULL,
          ip           text,
          user_agent   text
        );
        CREATE INDEX staff_sessions_user_idx ON staff_sessions (user_id);
        CREATE INDEX staff_sessions_expiry_idx ON staff_sessions (expires_at);

        -- Every login attempt, kept 30 days: the throttle counts the failures, and it is the login audit trail.
        CREATE TABLE login_attempts (
          id        bigserial PRIMARY KEY,
          username  text NOT NULL,
          ip        text,
          success   boolean NOT NULL,
          reason    text,
          at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX login_attempts_user_idx ON login_attempts (username, at);
        CREATE INDEX login_attempts_ip_idx ON login_attempts (ip, at);

        -- Who did a staff action (approve a reply, sync the catalogue, log in or out). NULL for agent actions.
        ALTER TABLE audit_log ADD COLUMN staff_user_id bigint REFERENCES staff_users(id);

        -- The Insights page numbers, computed by the worker every hour.
        CREATE TABLE insight_snapshots (
          id          bigserial PRIMARY KEY,
          computed_at timestamptz NOT NULL DEFAULT now(),
          data        jsonb NOT NULL
        );
        CREATE INDEX insight_snapshots_recent_idx ON insight_snapshots (computed_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS insight_snapshots;
        ALTER TABLE audit_log DROP COLUMN IF EXISTS staff_user_id;
        DROP TABLE IF EXISTS login_attempts, staff_sessions, staff_users;
        DROP INDEX IF EXISTS audit_created_idx;
        DROP INDEX IF EXISTS messages_created_idx;
        DROP INDEX IF EXISTS conversations_customer_recent_idx;
        ALTER TABLE conversations DROP COLUMN IF EXISTS internal;
        """
    )
