import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ParseMode
from aiogram.methods import SendMessage

from config import BOT_TOKEN
from utils.anti_spam import AntiSpamMiddleware
from utils.middlewares import BanMiddleware

logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# ===== Anti-spam (outer, срабатывает до FSM) =====
dp.message.outer_middleware(AntiSpamMiddleware(msg_interval=1.5, cb_interval=1.0))
dp.callback_query.outer_middleware(AntiSpamMiddleware(msg_interval=1.5, cb_interval=1.0))

# ===== Ban =====
_ban_mw = BanMiddleware()
dp.message.middleware(_ban_mw)
dp.callback_query.middleware(_ban_mw)


# ===== Auto-delete: удаляем предыдущее текстовое сообщение бота =====
_last_bot_msgs: dict = {}


class AutoCleanSessionMiddleware(BaseRequestMiddleware):
    """Перед send_message удаляет предыдущее сообщение бота в том же чате."""

    async def __call__(self, make_request, bot_, method):
        if isinstance(method, SendMessage):
            chat_id = method.chat_id
            if isinstance(chat_id, int) and chat_id > 0:
                prev = _last_bot_msgs.pop(chat_id, None)
                if prev:
                    try:
                        await bot_.delete_message(chat_id, prev)
                    except Exception:
                        pass
        response = await make_request(bot_, method)
        if isinstance(method, SendMessage):
            chat_id = method.chat_id
            if isinstance(chat_id, int) and chat_id > 0:
                try:
                    _last_bot_msgs[chat_id] = response.message_id
                except Exception:
                    pass
        return response


bot.session.middleware(AutoCleanSessionMiddleware())