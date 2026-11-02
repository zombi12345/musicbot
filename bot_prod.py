"""Render webhook entry — свой Bot/DP/loop, без зависимости от loader.py."""
import asyncio
import logging
import os
import threading

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from flask import Flask, abort, jsonify, request

from config import BOT_TOKEN, LOG_LEVEL, PORT, WEBHOOK_PATH, WEBHOOK_SECRET
from database.postgres_db import init_db
from handlers import setup_routers

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# ==== ОДИН loop, ОДИН Bot, ОДИН DP — всё внутри bot_prod ====
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
setup_routers(dp)

# init_db ДО старта Flask (pool создаётся в _loop)
_loop.run_until_complete(init_db())
logger.info("Bot/DP/DB ready")

# Запускаем loop в фоне
threading.Thread(target=_loop.run_forever, daemon=True).start()

app = Flask(__name__)


def _run(coro, timeout=50):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


@app.route("/health")
def health():
    return jsonify(status="ok"), 200


@app.route("/version")
def version():
    return jsonify(
        git_commit=os.getenv("RENDER_GIT_COMMIT", "local"),
        git_branch=os.getenv("RENDER_GIT_BRANCH", "main"),
        has_admin=True,
        has_music=True,
        has_stars=True,
        has_broadcast=True,
        has_playlists=True,
        has_lyrics=True,
        has_recognize=True,
        mode="webhook",
    ), 200


@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)
    try:
        data = request.get_json(force=True)
        update = Update.model_validate(data)
        _run(dp.feed_update(bot, update), timeout=50)
        return "", 200
    except Exception:
        logger.exception("webhook error")
        return "", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)