from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from database.postgres_db import get_pool
from keyboards.admin import admin_menu
from locales import t
from utils.checks import is_admin

router = Router(name="admin")


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        await message.answer(t("admin_no_access"))
        return
    await message.answer(t("admin_title"), reply_markup=admin_menu())


@router.callback_query(F.data == "adm_stats")
async def cb_stats(call: CallbackQuery) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer(t("admin_no_access"), show_alert=True)
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
        active = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE last_seen > NOW() - INTERVAL '7 days'"
        )
        banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned=TRUE")
    text = (
        f"<b>{t('stats_title')}</b>\n\n"
        f"{t('stats_total')}: <b>{total}</b>\n"
        f"{t('stats_active')}: <b>{active}</b>\n"
        f"{t('stats_banned')}: <b>{banned}</b>"
    )
    await call.message.edit_text(text)
    await call.answer()


@router.callback_query(F.data == "adm_broadcast")
async def cb_broadcast(call: CallbackQuery) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer(t("admin_no_access"), show_alert=True)
        return
    await call.message.edit_text("📢 Рассылка - в разработке (D-2).")
    await call.answer()


@router.callback_query(F.data == "adm_users")
async def cb_users(call: CallbackQuery) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer(t("admin_no_access"), show_alert=True)
        return
    await call.message.edit_text("👥 Пользователи - в разработке (D-2).")
    await call.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
    await message.answer(f"{t('stats_title')}: всего <b>{total}</b> юзеров.")