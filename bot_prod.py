import asyncio
import logging
import os
import threading

from aiogram.types import Update
from flask import Flask, abort, jsonify, request

from config import LOG_LEVEL, PORT, WEBHOOK_PATH, WEBHOOK_SECRET
from database.postgres_db import init_db
from handlers import setup_routers
from loader import bot, dp

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Отдельный loop в фоновом потоке - корректный паттерн Flask + aiogram + gthread
_loop = asyncio.new_event_loop()
_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_thread.start()

setup_routers(dp)
asyncio.run_coroutine_threadsafe(init_db(), _loop).result(timeout=30)


def _run(coro, timeout=60):
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
        has_music=False,
        has_broadcast=False,
    ), 200


@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)
    try:
        update = Update.model_validate(request.get_json(force=True))
        _run(dp.feed_update(bot, update), timeout=60)
        return "", 200
    except Exception:
        logger.exception("webhook error")
        return "", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)