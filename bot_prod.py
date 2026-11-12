"""bot_prod.py — aiohttp webhook (без Flask, без gunicorn, чистый asyncio)."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import BOT_TOKEN, LOG_LEVEL, PORT, WEBHOOK_PATH, WEBHOOK_SECRET, WEBHOOK_URL
from database.postgres_db import init_db
from handlers import setup_routers

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    await init_db()
    logger.info("DB ready")
    if WEBHOOK_URL:
        url = f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}"
        try:
            await bot.set_webhook(url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True)
            logger.info("Webhook set: %s", url)
        except Exception:
            logger.exception("set_webhook failed")


async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down")
    await bot.session.close()


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def version(request: web.Request) -> web.Response:
    return web.json_response({
        "git_commit": os.getenv("RENDER_GIT_COMMIT", "local"),
        "git_branch": os.getenv("RENDER_GIT_BRANCH", "main"),
        "has_admin": True,
        "has_music": True,
        "has_stars": True,
        "has_playlists": True,
        "has_lyrics": True,
        "has_recognize": True,
        "mode": "aiohttp",
    })


async def debug_cookies(request: web.Request) -> web.Response:
    import os
    from services.downloader import COOKIES_FILE
    info = {
        "env_set": bool(os.getenv("YT_COOKIES_BASE64")),
        "env_length": len(os.getenv("YT_COOKIES_BASE64", "")),
        "cookies_file": COOKIES_FILE,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        try:
            info["file_size"] = os.path.getsize(COOKIES_FILE)
            with open(COOKIES_FILE, "r", encoding="utf-8", errors="ignore") as f:
                info["first_200"] = f.read(200)
        except Exception as e:
            info["file_error"] = str(e)
    return web.json_response(info)


async def main() -> None:
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    setup_routers(dp)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()

    # Webhook
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
    handler.register(app, path=WEBHOOK_PATH)

    # Health / version
    app.router.add_get("/health", health)
    app.router.add_get("/version", version)
    app.router.add_get("/debug_cookies", debug_cookies)

    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("aiohttp server running on port %s", PORT)

    try:
        await asyncio.Event().wait()  # бесконечно
    finally:
        await runner.cleanup()



if __name__ == "__main__":
    asyncio.run(main())