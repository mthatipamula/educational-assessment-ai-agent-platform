import json
import logging
from pathlib import Path

import asyncpg

from . import config

log = logging.getLogger(__name__)
SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
pool: asyncpg.Pool | None = None


async def _init(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def connect() -> asyncpg.Pool:
    global pool
    pool = await asyncpg.create_pool(config.DB_DSN, min_size=1, max_size=10, init=_init)
    async with pool.acquire() as conn:
        await conn.execute((SQL_DIR / "schema.sql").read_text())
        if config.SEED_DEMO_DATA and await conn.fetchval("SELECT count(*) FROM standards") == 0:
            await conn.execute((SQL_DIR / "seed.sql").read_text())
            log.info("Loaded demo standards, passages, items and students")
    return pool


def vector_literal(values: list[float]) -> str:
    """pgvector text format; passed with a ::vector cast."""
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


def row(r) -> dict | None:
    return dict(r) if r is not None else None
