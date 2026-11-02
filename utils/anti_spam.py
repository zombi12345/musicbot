"""Anti-spam middleware: удаляет спам-сообщения юзера + отвечает на callback."""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, interval: float = 1.5, delete_spam: bool = True):
        self.interval = interval
        self.delete_spam = delete_spam
        self.last: dict = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        now = time.time()
        last = self.last.get(user.id, 0)

        if now - last < self.interval:
            # Drop + cleanup
            logger.debug("antispam drop user=%s type=%s",
                         user.id, type(event).__name__)

            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()  # убирает спиннер
                except Exception:
                    pass
            elif isinstance(event, Message) and self.delete_spam:
                # Удаляем спам-сообщение юзера
                try:
                    await event.delete()
                except Exception:
                    pass
            return None

        self.last[user.id] = now
        return await handler(event, data)