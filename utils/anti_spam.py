"""Anti-spam middleware."""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.last: dict = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)
        now = time.time()
        last = self.last.get(user.id, 0)
        if now - last < self.interval:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            return None
        self.last[user.id] = now
        return await handler(event, data)