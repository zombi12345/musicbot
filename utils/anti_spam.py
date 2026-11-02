"""Anti-spam: блокирует только повторные одинаковые сообщения."""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, msg_interval: float = 0.6, cb_interval: float = 0.6):
        self.msg_interval = msg_interval
        self.cb_interval = cb_interval
        self.last_msg: dict = {}  # uid -> (text, time)
        self.last_cb: dict = {}   # uid -> time

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        now = time.time()

        if isinstance(event, CallbackQuery):
            last = self.last_cb.get(user.id, 0)
            if now - last < self.cb_interval:
                try:
                    await event.answer()
                except Exception:
                    pass
                return None
            self.last_cb[user.id] = now
            return await handler(event, data)

        if isinstance(event, Message):
            last_text, last_time = self.last_msg.get(user.id, ("", 0))
            current_text = (event.text or "").strip()

            # Блокируем ТОЛЬКО если тот же текст и быстрее интервала
            if (
                current_text
                and current_text == last_text
                and now - last_time < self.msg_interval
            ):
                logger.debug("antispam drop duplicate: user=%s", user.id)
                try:
                    await event.delete()
                except Exception:
                    pass
                return None

            self.last_msg[user.id] = (current_text, now)
            return await handler(event, data)

        return await handler(event, data)