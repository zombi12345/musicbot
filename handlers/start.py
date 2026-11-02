from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from database.postgres_db import get_pool
from keyboards.main import main_menu
from locales import t
from utils.checks import is_banned

router = Router(name="start")


async def _register_user(message: Message) -> None:
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
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
            )
    except Exception:
        pass


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if await is_banned(message.from_user.id):
        await message.answer(t("banned_alert"))
        return
    await _register_user(message)
    await message.answer(
        t("start_hello", name=message.from_user.first_name or "друг"),
        reply_markup=main_menu(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer(t("menu_title"), reply_markup=main_menu())


@router.message(F.text == "🎵 Скачать трек")
async def btn_download(message: Message) -> None:
    await message.answer(t("download_hint"))


@router.message(F.text == "❓ Помощь")
async def btn_help(message: Message) -> None:
    await message.answer(t("help_text"))


@router.message(F.text == "📊 Мой профиль")
async def btn_profile(message: Message) -> None:
    uid = message.from_user.id
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT created_at FROM users WHERE user_id=$1", uid
            )
        reg = row["created_at"].strftime("%d.%m.%Y") if row else "—"
    except Exception:
        reg = "—"
    await message.answer(
        f"👤 <b>Профиль</b>\n\nID: <code>{uid}</code>\n"
        f"Имя: {message.from_user.first_name or '—'}\nРегистрация: {reg}"
    )