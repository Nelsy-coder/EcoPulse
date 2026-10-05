from __future__ import with_statement
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# add project directory to path
proj_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if proj_path not in sys.path:
    sys.path.insert(0, proj_path)

# Import the Flask app and SQLAlchemy metadata
try:
    from ecopulse_app import app, db
    target_metadata = db.metadata
except Exception as e:
    print('Failed to import app or db for Alembic env:', e)
    target_metadata = None

# Override sqlalchemy.url with value from Flask app config when available
if 'sqlalchemy.url' not in config.get_section(config.config_ini_section) or not config.get_main_option('sqlalchemy.url'):
    try:
        config.set_main_option('sqlalchemy.url', app.config.get('SQLALCHEMY_DATABASE_URI'))
    except Exception:
        pass


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
