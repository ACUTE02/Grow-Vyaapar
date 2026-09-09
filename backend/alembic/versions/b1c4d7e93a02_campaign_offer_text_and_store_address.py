"""Campaign offer text and store address

Two columns for the poster feature: the offer a shopkeeper wants printed on
the image, and the street address to print under the store name. Both are
nullable - an existing campaign has no offer, and a store that has not filled
in an address simply gets one fewer line on the poster.

Revision ID: b1c4d7e93a02
Revises: 4e24ea21b264
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1c4d7e93a02"
down_revision = "4e24ea21b264"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("offer_text", sa.String(length=140), nullable=True))
    op.add_column("stores", sa.Column("address", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "address")
    op.drop_column("campaigns", "offer_text")
