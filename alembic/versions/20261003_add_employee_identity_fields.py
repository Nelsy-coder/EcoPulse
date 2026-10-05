"""Add identity fields for employees.

Revision ID: 20261003_employee_identity
Revises:
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa


revision = '20261003_employee_identity'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('id_number', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('full_name', sa.String(length=200), nullable=True))
    op.add_column('user_registration_requests', sa.Column('id_number', sa.String(length=50), nullable=True))
    op.add_column('user_registration_requests', sa.Column('full_name', sa.String(length=200), nullable=True))


def downgrade():
    op.drop_column('user_registration_requests', 'full_name')
    op.drop_column('user_registration_requests', 'id_number')
    op.drop_column('users', 'full_name')
    op.drop_column('users', 'id_number')