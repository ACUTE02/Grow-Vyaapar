"""Transaction idempotency key

A client sends one key per checkout, and (store_id, idempotency_key) is unique,
so a retried request cannot become a second bill. The column is nullable and
NULLs are distinct in a unique index on both SQLite and Postgres, so every
transaction written before this migration - and every sale the seed writes
through the service directly - keeps working with no key at all.

Safe on existing data: nothing is rewritten and no row can violate the new
constraint, because they all get NULL.

Revision ID: c73f1a5b8e40
Revises: b1c4d7e93a02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c73f1a5b8e40"
down_revision = "b1c4d7e93a02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table so SQLite gets a table rebuild rather than an
    # unsupported ALTER; on Postgres it is a plain ADD COLUMN plus an index.
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=64), nullable=True))
        batch.create_unique_constraint(
            "uq_txn_store_idempotency", ["store_id", "idempotency_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("uq_txn_store_idempotency", type_="unique")
        batch.drop_column("idempotency_key")
