import logging

import config
from database.postgres_db import get_pool

logger = logging.getLogger(__name__)


async def is_admin(user_id: int) -> bool:
    if user_id in config.ADMIN_IDS:
        return True
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchval("SELECT 1 FROM admins WHERE user_id=$1", user_id)
        return bool(row)
    except Exception:
        logger.exception("is_admin check failed for %s", user_id)
        return False


async def is_banned(user_id: int) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT is_banned FROM users WHERE user_id=$1", user_id
            )
        return bool(row)
    except Exception:
        return False