"""Create a fresh, migrated, isolated database for tests (pytest and Playwright).

Usage: python -m app.testdb <database_name> [--seed] [--serve PORT]
Never touches the database named in the normal DATABASE_URL.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import psycopg
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.config import get_settings

API_ROOT = Path(__file__).resolve().parents[1]


def test_database_url(name: str) -> str:
    return make_url(get_settings().database_url).set(database=name).render_as_string(False)


def reset_database(name: str) -> None:
    """Drop and recreate `name`, then migrate to head. Refuses names that are not test DBs."""
    if not re.fullmatch(r"[a-z0-9_]+_(test|e2e)", name):
        raise ValueError(f"Refusing to reset '{name}': name must end in _test or _e2e")
    url = make_url(get_settings().database_url).set(drivername="postgresql", database="postgres")
    with psycopg.connect(url.render_as_string(False), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')
    os.environ["DATABASE_URL"] = test_database_url(name)
    get_settings.cache_clear()
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(cfg, "head")


def main() -> None:
    from app.db.session import get_engine
    from app.seed import seed

    name = sys.argv[1]
    reset_database(name)
    if "--seed" in sys.argv:

        async def run() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            engine = get_engine()
            async with async_sessionmaker(engine)() as session:
                await seed(session)
            await engine.dispose()

        asyncio.run(run())
    print(f"Test database '{name}' ready", flush=True)
    if "--serve" in sys.argv:
        import uvicorn

        port = int(sys.argv[sys.argv.index("--serve") + 1])
        uvicorn.run("app.main:app", port=port, log_level="warning")


if __name__ == "__main__":
    main()
