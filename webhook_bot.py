import asyncio
import logging

from database.postgres_db import init_db
from handlers import setup_routers
from loader import bot, dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    setup_routers(dp)
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass