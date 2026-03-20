"""add scan_presets

Revision ID: 287345549674
Revises: 3d754888ad09
Create Date: (auto)

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "287345549674"
down_revision = "3d754888ad09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_presets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),

        sa.Column("name", sa.String(length=80), nullable=False),

        sa.Column("option_type", sa.String(length=10), nullable=False),
        sa.Column("delta_target", sa.Float(), nullable=False),

        sa.Column("indicators", sa.JSON(), nullable=False),

        sa.Column("use_trend_filter", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("trend_type", sa.String(length=10), nullable=True),
        sa.Column("trend_length", sa.Integer(), nullable=True),

        sa.Column("use_rsi_filter", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("rsi_length", sa.Integer(), nullable=True),
        sa.Column("rsi_min", sa.Float(), nullable=True),
        sa.Column("rsi_max", sa.Float(), nullable=True),

        sa.Column("description", sa.String(length=255), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),

        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scan_presets_id"), "scan_presets", ["id"], unique=False)
    op.create_index(op.f("ix_scan_presets_user_id"), "scan_presets", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scan_presets_user_id"), table_name="scan_presets")
    op.drop_index(op.f("ix_scan_presets_id"), table_name="scan_presets")
    op.drop_table("scan_presets")