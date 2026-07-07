"""Add staff profile columns

Revision ID: 35c697480eed
Revises: dabba7d85a25
Create Date: 2026-07-06 22:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '35c697480eed'
down_revision = 'dabba7d85a25'
branch_labels = None
depends_on = None


def upgrade():
    # Surgically add only the three profile columns to core.users
    op.add_column('users', sa.Column('name', sa.String(length=100), nullable=True), schema='core')
    op.add_column('users', sa.Column('designation', sa.String(length=100), nullable=True), schema='core')
    op.add_column('users', sa.Column('mobile', sa.String(length=50), nullable=True), schema='core')


def downgrade():
    # Surgically remove the columns if downgraded
    op.drop_column('users', 'mobile', schema='core')
    op.drop_column('users', 'designation', schema='core')
    op.drop_column('users', 'name', schema='core')