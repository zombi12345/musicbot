"""Anti-spam middleware: 0.5s между апдейтами от юзера."""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, interval: float = 0.5, alert: bool = False):
        self.interval = interval
        self.alert = alert
        self.last: dict = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)
        now = time.time()
        last = self.last.get(user.id, 0)
        if now - last < self.interval:
            logger.debug("antispam drop: user=%s type=%s", user.id, type(event).__name__)
            if self.alert and isinstance(event, CallbackQuery):
                try:
                    await event.answer("⏳ Не так быстро", show_alert=False)
                except Exception:
                    pass
            return None
        self.last[user.id] = now
        return await handler(event, data)