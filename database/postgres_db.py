import logging
import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)
_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            ssl="require",
            statement_cache_size=0,
            min_size=1,
            max_size=5,
            timeout=30,
        )
        logger.info("DB pool created")
    return _pool


async def init_db():
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set - DB init skipped")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                lang TEXT DEFAULT 'ru',
                is_banned BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_seen TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT,
                added_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;
        """)
    logger.info("DB schema ready")