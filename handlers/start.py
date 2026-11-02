from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from database.postgres_db import get_pool
from keyboards.main import main_menu
from locales import t
from utils.checks import is_banned

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    uid = message.from_user.id
    if await is_banned(uid):
        await message.answer(t("banned_alert"))
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, first_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_seen = NOW()
                """,
                uid,
                message.from_user.username,
                message.from_user.first_name,
            )
    except Exception:
        pass
    await message.answer(
        t("start_hello", name=message.from_user.first_name or "друг"),
        reply_markup=main_menu(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer(t("menu_title"), reply_markup=main_menu())