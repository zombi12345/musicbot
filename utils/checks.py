import logging

import config
from database import postgres_db as db

logger = logging.getLogger(__name__)


async def is_banned(user_id: int) -> bool:
    try:
        user = await db.get_user(user_id)
        return bool(user and user.get("is_banned"))
    except Exception:
        logger.exception("is_banned failed")
        return False


async def is_admin(user_id: int) -> bool:
    if user_id in config.ADMIN_IDS:
        return True
    try:
        extra = await db.get_extra_admins()
        return user_id in extra
    except Exception:
        return False


async def is_main_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def has_access(user_id: int) -> bool:
    if config.FREE_MODE:
        return True
    try:
        return await db.is_paid(user_id)
    except Exception:
        return False


async def can_download(user_id: int):
    return await db.can_download(user_id)