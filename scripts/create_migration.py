"""Helper script to create an Alembic revision (autogenerate) and upgrade to head.

Usage:
    pip install -r requirements-dev.txt
    python scripts/create_migration.py "message"

If no message is provided, defaults to 'autogen'
"""
import sys
from alembic.config import Config
from alembic import command
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ALEMBIC_INI = os.path.join(PROJECT_ROOT, 'alembic.ini')


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else 'autogen'
    cfg = Config(ALEMBIC_INI)
    # Ensure config uses project path
    cfg.set_main_option('script_location', os.path.join(PROJECT_ROOT, 'alembic'))

    print('Creating revision (autogenerate) with message:', msg)
    command.revision(cfg, message=msg, autogenerate=True)
    print('Upgrading to head')
    command.upgrade(cfg, 'head')
    print('Done')


if __name__ == '__main__':
    main()
