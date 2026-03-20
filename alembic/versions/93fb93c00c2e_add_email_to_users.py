"""add email to users

Revision ID: 93fb93c00c2e
Revises: 1dd5ee8ce4d0
Create Date: 2026-02-23 22:05:55.637080

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '93fb93c00c2e'
down_revision: Union[str, Sequence[str], None] = '1dd5ee8ce4d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import sqlalchemy as sa
    from alembic import op

    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=False))
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    from alembic import op

    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email")
