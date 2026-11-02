import logging
from database.postgres_db import get_pool

logger = logging.getLogger(__name__)


async def get_cached(url_hash: str):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT file_id, title, performer, duration, platform "
                "FROM track_cache WHERE url_hash=$1",
                url_hash,
            )
            if row:
                await conn.execute(
                    "UPDATE track_cache SET hits = hits + 1 WHERE url_hash=$1",
                    url_hash,
                )
                return dict(row)
    except Exception:
        logger.exception("get_cached failed")
    return None


async def save_cached(url_hash, original_url, platform, title, performer, duration, file_id):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO track_cache
                (url_hash, original_url, platform, title, performer, duration, file_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (url_hash) DO UPDATE
                SET file_id = EXCLUDED.file_id,
                    title = EXCLUDED.title,
                    performer = EXCLUDED.performer,
                    duration = EXCLUDED.duration
                """,
                url_hash, original_url, platform, title or "", performer or "", duration or 0, file_id,
            )
    except Exception:
        logger.exception("save_cached failed")