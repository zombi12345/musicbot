from aiogram import Dispatcher

from handlers import admin, download, start


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(admin.router)
    dp.include_router(download.router)
    dp.include_router(start.router)