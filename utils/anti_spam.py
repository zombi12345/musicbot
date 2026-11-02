"""Anti-spam: удаляет ТОЛЬКО спам-кнопки, не ссылки."""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

# Тексты menu-кнопок (удаляем только их спам)
MENU_BUTTONS = {
    "🎵 Скачать трек", "🎤 Распознать",
    "📋 Плейлист", "📝 Текст песни",
    "📜 Мои треки", "📊 Профиль",
    "💎 Подписка", "💳 Баланс",
    "🎁 Триал", "💡 Как работает",
    "❓ Помощь", "👑 Админ-панель",
}


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, msg_interval: float = 1.5, cb_interval: float = 1.0):
        self.msg_interval = msg_interval
        self.cb_interval = cb_interval
        self.last_msg: dict = {}
        self.last_cb: dict = {}

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
            last = self.last_msg.get(user.id, 0)
            if now - last < self.msg_interval:
                # Удаляем ТОЛЬКО спам menu-кнопок
                if event.text and event.text.strip() in MENU_BUTTONS:
                    try:
                        await event.delete()
                    except Exception:
                        pass
                return None
            self.last_msg[user.id] = now
            return await handler(event, data)

        return await handler(event, data)