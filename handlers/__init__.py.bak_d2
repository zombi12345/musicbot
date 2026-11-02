from aiogram import Dispatcher

from handlers import admin, start


def setup_routers(dp: Dispatcher) -> None:
    # admin первым - у него специфичные фильтры
    dp.include_router(admin.router)
    dp.include_router(start.router)