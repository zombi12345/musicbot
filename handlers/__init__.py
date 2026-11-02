from aiogram import Dispatcher

from handlers import admin, admin_billing, download, recognize, start, user_menu


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(admin.router)
    dp.include_router(admin_billing.router)
    dp.include_router(user_menu.router)
    dp.include_router(recognize.router)
    dp.include_router(download.router)
    dp.include_router(start.router)