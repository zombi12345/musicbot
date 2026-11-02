import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

logger = logging.getLogger(__name__)


async def broadcast(bot: Bot, user_ids: list, text: str, on_progress=None) -> dict:
    stats = {"sent": 0, "blocked": 0, "failed": 0}
    total = len(user_ids)
    for i, uid in enumerate(user_ids, 1):
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            stats["sent"] += 1
        except TelegramForbiddenError:
            stats["blocked"] += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_message(uid, text, parse_mode="HTML")
                stats["sent"] += 1
            except Exception:
                stats["failed"] += 1
        except Exception:
            stats["failed"] += 1
        if on_progress and (i % 25 == 0 or i == total):
            try:
                await on_progress(i, total, stats)
            except Exception:
                pass
        await asyncio.sleep(0.04)
    return stats