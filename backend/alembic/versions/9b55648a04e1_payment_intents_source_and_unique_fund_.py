"""payment intents source and unique fund_signature

Revision ID: 9b55648a04e1
Revises: 9a82e72d052c
Create Date: 2026-11-14 13:19:12.091337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '9b55648a04e1'
down_revision: Union[str, Sequence[str], None] = '9a82e72d052c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE payment_intents ADD COLUMN IF NOT EXISTS source VARCHAR")
    op.create_index(op.f('ix_payment_intents_fund_signature'), 'payment_intents', ['fund_signature'], unique=True)

def downgrade() -> None:
    op.drop_index(op.f('ix_payment_intents_fund_signature'), table_name='payment_intents')
    op.drop_column('payment_intents', 'source')
