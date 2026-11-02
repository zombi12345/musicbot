import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from utils.anti_spam import AntiSpamMiddleware
from utils.middlewares import BanMiddleware

logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# Anti-spam: 0.6s для сообщений (только дубли), 0.6s для callback
dp.message.outer_middleware(AntiSpamMiddleware(msg_interval=0.6, cb_interval=0.6))
dp.callback_query.outer_middleware(AntiSpamMiddleware(msg_interval=0.6, cb_interval=0.6))

# Ban
_ban_mw = BanMiddleware()
dp.message.middleware(_ban_mw)
dp.callback_query.middleware(_ban_mw)