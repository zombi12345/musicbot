import logging

import config
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import postgres_db as db
from keyboards.main import main_menu
from utils.checks import is_admin, is_banned

router = Router(name="start")
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    uid = message.from_user.id
    if await is_banned(uid):
        await message.answer("⛔ Вы заблокированы.")
        return
    await db.upsert_user(
        uid,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    admin = await is_admin(uid)
    name = message.from_user.first_name or "друг"
    paid = await db.is_paid(uid)
    mode = await db.get_billing_mode()
    if config.FREE_MODE or paid:
        pay_line = "  💎 У тебя <b>безлимит</b> — просто пришли ссылку"
    elif mode.get("subscription_enabled") and not mode.get("pay_per_use_enabled"):
        pay_line = "  💎 Подписка /sub — безлимит"
    elif mode.get("subscription_enabled") and mode.get("pay_per_use_enabled"):
        pay_line = "  💎 Подписка /sub — безлимит · 💳 Или /balance (по действиям)"
    else:
        pay_line = "  💳 Баланс — по действиям (/buy)"
    if await db.get_trial_enabled_or_false() if False else (await db.get_trial()).get("enabled"):
        user = await db.get_user(uid)
        if user and not user.get("trial_used"):
            pay_line += "\n  🎁 Триал /trial — бесплатно"
    text = (
        f"🎵 <b>Привет, {name}!</b>\n\n"
        "Я умею качать музыку из:\n"
        "  • Spotify\n"
        "  • SoundCloud\n"
        "  • YouTube\n"
        "  • Яндекс.Музыка\n"
        "  • Bandcamp, VK, Mixcloud\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Что умею:</b>\n"
        "  🎵 <b>Скачивать треки</b> — пришли ссылку\n"
        "  🎤 <b>Распознавать музыку</b> — голосовое 10-15 сек\n"
        "  📜 <b>Хранить историю</b> — последние 10 треков\n"
        "  📋 <b>Скачивать плейлисты</b> — до 20 треков\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Оплата:</b>\n"
        "{pay_line}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 Меню внизу. Или просто пришли ссылку.\n"
        "💡 <b>Как работает:</b> /help или кнопка «💡 Как работает»"
    )
    await message.answer(text, reply_markup=main_menu(is_admin=admin))


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    admin = await is_admin(message.from_user.id)
    await message.answer(
        "🏠 <b>Главное меню</b>",
        reply_markup=main_menu(is_admin=admin),
    )


@router.message(F.text == "🎵 Скачать трек")
async def btn_download_hint(message: Message) -> None:
    text = (
        "🎵 <b>Скачать трек</b>\n\n"
        "Пришли ссылку на трек из любого сервиса:\n\n"
        "<b>Spotify</b>\n"
        "  <code>open.spotify.com/track/...</code>\n"
        "  <code>open.spotify.com/album/...</code>\n"
        "  <code>open.spotify.com/playlist/...</code>\n\n"
        "<b>SoundCloud</b>\n"
        "  <code>soundcloud.com/artist/track</code>\n"
        "  <code>soundcloud.com/artist/sets/...</code>\n\n"
        "<b>YouTube</b>\n"
        "  <code>youtube.com/watch?v=...</code>\n"
        "  <code>youtu.be/...</code>\n\n"
        "<b>Яндекс.Музыка</b>\n"
        "  <code>music.yandex.ru/album/.../track/...</code>\n\n"
        "<b>Bandcamp, VK Музыка, Mixcloud</b> — тоже работают\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 Просто скопируй ссылку из «Поделиться» и вставь в чат.\n"
        "Плейлисты тоже работают — до 20 треков."
    )
    await message.answer(text)


@router.message(F.text == "🎤 Распознать")
async def btn_recognize_hint(message: Message) -> None:
    text = (
        "🎤 <b>Распознать музыку</b>\n\n"
        "Услышал трек — не знаешь название? Я найду.\n\n"
        "<b>Как:</b>\n"
        "1. Запиши голосовое 10-15 сек\n"
        "2. Отправь в чат\n"
        "3. Жди — распознаю и скачаю\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Советы:</b>\n"
        "  • Минимум 10 сек\n"
        "  • Ближе к источнику звука\n"
        "  • Лучше если слышны слова\n\n"
        "💡 Можно отправить <b>аудио</b> или <b>видео</b>\n"
        "💳 Не нашёл — <b>не списывается</b>"
    )
    await message.answer(text)


@router.message(F.text == "📊 Профиль")
async def btn_profile(message: Message) -> None:
    uid = message.from_user.id
    user = await db.get_user(uid)
    if not user:
        await message.answer("⚠️ Сначала /start")
        return
    paid = await db.is_paid(uid)
    sub_end = user["subscription_end"].strftime("%d.%m.%Y") if user["subscription_end"] else "—"
    balance = await db.get_balance(uid)
    total_downloads = await db.count_user_downloads(uid)
    mode = await db.get_billing_mode()
    free_limit = int(mode.get("free_actions_per_day", 0))
    free_used = await db.get_total_free_actions_used(uid)
    trial = await db.get_trial()
    trial_status = "✅ использован" if user["trial_used"] else (
        "🎁 доступен" if trial.get("enabled") else "❌ отключён"
    )

    status = "💎 Premium" if paid else "🆓 Бесплатный"
    text = (
        f"👤 <b>Мой профиль</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📝 Имя: {user['first_name'] or '—'}\n"
        f"📅 С нами с: {user['created_at'].strftime('%d.%m.%Y')}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Статус:</b> {status}\n"
    )
    if paid:
        text += f"📅 Подписка до: <b>{sub_end}</b>\n"
    text += (
        f"💳 Баланс: <b>{balance}⭐</b>\n"
        f"🎁 Триал: {trial_status}\n"
    )
    if free_limit > 0:
        text += f"🆓 Бесплатных сегодня: <b>{max(0, free_limit - free_used)}/{free_limit}</b>\n"
    text += (
        f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"📜 Скачано треков: <b>{total_downloads}</b>\n\n"
        f"💡 <b>Действия:</b>\n"
        f"  • /sub — подписка\n"
        f"  • /balance — баланс\n"
        f"  • /buy — пополнить\n"
        f"  • /trial — активировать триал\n"
    )
    await message.answer(text)


@router.message(F.text == "👑 Админ-панель")
async def btn_admin(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    from keyboards.admin import admin_menu
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu())