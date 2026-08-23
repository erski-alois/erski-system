import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 這個專案沒有用SQLAlchemy ORM(維持原本db.py那層薄的sqlite3/psycopg2相容層，
# 不做大改動)，所以這裡沒有target_metadata可以autogenerate比對 — migration
# 一律用手寫SQL(op.execute(...))的方式新增在alembic/versions/底下，不要用
# `alembic revision --autogenerate`(那個指令在這個專案裡不會產生正確結果)。
target_metadata = None

# 資料庫連線字串一律從DATABASE_URL環境變數讀取(跟db.py用同一個環境變數)，
# 不要寫死在alembic.ini裡 — 這樣本機測試/正式環境用同一份alembic設定即可，
# 只要環境變數不同，migration就會套用到對的資料庫。
_database_url = os.environ.get("DATABASE_URL", "").strip()
if _database_url:
    config.set_main_option("sqlalchemy.url", _database_url)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
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


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
