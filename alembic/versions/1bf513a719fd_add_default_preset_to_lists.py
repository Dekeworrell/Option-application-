"""add default preset to lists

Revision ID: 1bf513a719fd
Revises: 287345549674
Create Date: 2026-03-12 16:22:28.205597

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1bf513a719fd"
down_revision: Union[str, Sequence[str], None] = "287345549674"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("lists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("default_preset_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_lists_default_preset_id",
            "scan_presets",
            ["default_preset_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("lists", schema=None) as batch_op:
        batch_op.drop_constraint("fk_lists_default_preset_id", type_="foreignkey")
        batch_op.drop_column("default_preset_id")