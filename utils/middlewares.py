from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from utils.checks import is_banned


class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data):
        user = data.get("event_from_user")
        if user and await is_banned(user.id):
            return None
        return await handler(event, data)