import html
import logging

import config
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import postgres_db as db
from keyboards.main import (main_inline, 
    back_to_help,
    cancel_kb,
    help_inline,
    main_menu,
    sub_inline,
    tracks_inline,
)
from utils.checks import is_admin, is_banned
from states import UserLyricsStates

router = Router(name="user_menu")
logger = logging.getLogger(__name__)


def _e(v):
    return html.escape(str(v)) if v is not None else "—"


async def _menu(uid: int):
    admin = await is_admin(uid)
    return main_menu(is_admin=admin)


async def _price_lines(uid: int) -> str:
    paid = await db.is_paid(uid)
    if config.FREE_MODE:
        return "💎 <b>У тебя безлимит</b>\n"
    if paid:
        return "💎 <b>У тебя активна подписка — безлимит</b>\n"
    mode = await db.get_billing_mode()
    if mode.get("subscription_enabled") and not mode.get("pay_per_use_enabled"):
        return "💎 <b>Оформи подписку /sub</b> — безлимит\n"
    if mode.get("subscription_enabled") and mode.get("pay_per_use_enabled"):
        prices = await db.get_action_prices()
        lines = "💡 <b>Два варианта:</b>\n"
        lines += "  💎 Подписка /sub — безлимит\n"
        lines += "  💳 Или за действие:\n"
        for k, t in config.ACTION_KEYS.items():
            lines += f"     • {t}: {prices.get(k, 0)}⭐\n"
        return lines
    prices = await db.get_action_prices()
    lines = "📋 <b>Цены за действие:</b>\n"
    for k, t in config.ACTION_KEYS.items():
        lines += f"  • {t}: {prices.get(k, 0)}⭐\n"
    return lines


# ============================================================
# CANCEL
# ============================================================

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    menu = await _menu(message.from_user.id)
    await message.answer("❌ Отменено.\n\n🏠 Меню внизу.", reply_markup=menu)


@router.callback_query(F.data == "user:cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    menu = await _menu(call.from_user.id)
    await call.message.answer("❌ Отменено.\n\n🏠 Меню внизу.", reply_markup=menu)
    await call.answer()


@router.callback_query(F.data == "user:recognize_cancel")
async def cb_recog_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    menu = await _menu(call.from_user.id)
    await call.message.answer("❌ Распознавание отменено.\n\n🏠 Меню внизу.", reply_markup=menu)
    await call.answer()


@router.callback_query(F.data == "user:lyrics_cancel")
async def cb_lyrics_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    menu = await _menu(call.from_user.id)
    await call.message.answer("❌ Отменено.\n\n🏠 Меню внизу.", reply_markup=menu)
    await call.answer()


# ============================================================
# 📜 МОИ ТРЕКИ
# ============================================================

async def _send_tracks(message: Message, uid: int):
    tracks = await db.get_user_downloads(uid, limit=10)
    total = await db.count_user_downloads(uid)

    if not tracks:
        text = (
            "📜 <b>Мои треки</b>\n\n"
            "Ты пока ничего не скачивал.\n\n"
            "💡 <b>Как начать:</b>\n"
            "  • Пришли ссылку на трек\n"
            "  • Или нажми 🎵 в меню\n"
            "  • Или 🎤 для распознавания"
        )
        await message.answer(text, reply_markup=tracks_inline(False))
        return

    text = (
        f"📜 <b>Мои треки</b>\n\n"
        f"Всего: <b>{total}</b>\n"
        f"Последние {len(tracks)}:\n\n"
    )
    for i, t in enumerate(tracks, 1):
        title = _e(t["title"] or "?")[:50]
        artist = _e(t["performer"] or "?")[:40]
        plat = t["platform"] or "?"
        date = t["downloaded_at"].strftime("%d.%m %H:%M") if t["downloaded_at"] else "?"
        text += f"{i}. <b>{artist}</b> — {title}\n"
        text += f"   <code>{plat}</code> · {date}\n"
    text += "\n💡 Кэш: повторная отправка той же ссылки — <b>бесплатно</b>"
    await message.answer(text, reply_markup=tracks_inline(True))


@router.message(F.text == "📜 Мои треки")
async def btn_my_tracks(message: Message) -> None:
    if await is_banned(message.from_user.id):
        return
    await _send_tracks(message, message.from_user.id)


@router.callback_query(F.data == "user:tracks_refresh")
async def cb_tracks_refresh(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:
        pass
    await _send_tracks(call.message, call.from_user.id)
    await call.answer()


# ============================================================
# 💎 ПОДПИСКА
# ============================================================

async def _send_sub(message: Message, uid: int, edit: bool = False):
    pricing = await db.get_pricing()
    mode = await db.get_billing_mode()
    paid = await db.is_paid(uid)
    balance = await db.get_balance(uid)

    sub_end = "—"
    if paid:
        user = await db.get_user(uid)
        if user and user.get("subscription_end"):
            sub_end = user["subscription_end"].strftime("%d.%m.%Y")

    text = "💎 <b>Подписка Premium</b>\n\n"
    if paid:
        text += f"✅ <b>Активна</b> до <b>{sub_end}</b>\n\n"
    else:
        text += f"🆓 Статус: <b>бесплатный</b>\n"
        text += f"💳 Баланс: <b>{balance}⭐</b>\n\n"

    if mode.get("subscription_enabled"):
        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        text += "<b>Что даёт:</b>\n"
        text += "  ✅ Безлимит на всё\n"
        text += "  ✅ Не нужно платить за каждое действие\n\n"
        text += "<b>Тарифы:</b>\n"
        for key in ["7", "30", "90"]:
            if key in pricing:
                info = pricing[key]
                per_day = round(info["stars"] / info["days"], 1)
                text += f"  💎 {info['days']}д — <b>{info['stars']}⭐</b> ({per_day}⭐/день)\n"
        if not paid:
            text += "\n⚠️ <i>Оплата Stars — скоро</i>"
        kb = sub_inline(pricing, True)
    else:
        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        text += "⚠️ <b>Подписка отключена</b>\n\n"
        text += await _price_lines(uid)
        kb = sub_inline(pricing, False)

    await message.answer(text, reply_markup=kb)


@router.message(Command("sub"))
@router.message(F.text == "💎 Подписка")
async def btn_sub(message: Message) -> None:
    if await is_banned(message.from_user.id):
        return
    await _send_sub(message, message.from_user.id)


@router.callback_query(F.data.startswith("user:sub:"))
async def cb_sub_plan(call: CallbackQuery) -> None:
    plan_key = call.data.split(":")[-1]
    pricing = await db.get_pricing()
    info = pricing.get(plan_key)
    if not info:
        await call.answer("Тариф недоступен", show_alert=True)
        return
    await call.answer(
        f"Оплата {info['days']}д за {info['stars']}⭐ скоро.\n"
        f"Пока напиши админу.",
        show_alert=True,
    )


# ============================================================
# 💳 БАЛАНС
# ============================================================

async def _send_balance(message: Message, uid: int, edit: bool = False) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    bal = await db.get_balance(uid)
    txs = await db.get_transactions(uid, limit=5)
    mode = await db.get_billing_mode()
    free_limit = int(mode.get("free_actions_per_day", 0))
    free_used = await db.get_total_free_actions_used(uid)

    text = "💳 <b>Баланс</b>\n\n"
    text += f"💰 Текущий: <b>{bal}⭐</b>\n"
    if free_limit > 0:
        text += f"🎁 Бесплатных сегодня: <b>{max(0, free_limit - free_used)}/{free_limit}</b>\n"

    text += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    text += await _price_lines(uid)
    text += "\n💡 <b>Кэш бесплатно</b> — повторный трек не списывает ⭐\n"

    if txs:
        text += "\n━━━━━━━━━━━━━━━━━━━━━\n<b>Последние операции:</b>\n"
        for tx in txs:
            sign = "+" if tx["amount"] > 0 else ""
            emoji = {"topup": "➕", "charge": "💳", "manual": "✏️"}.get(tx["kind"], "•")
            act = f" · {tx['action']}" if tx["action"] else ""
            text += f"  {emoji} {sign}{tx['amount']}⭐{act}\n"

    kb_rows = [
        [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="user:buy")],
    ]
    if mode.get("subscription_enabled"):
        kb_rows.append([InlineKeyboardButton(text="💎 Подписка (безлимит)", callback_data="user:menu_sub")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="user:menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb)

@router.message(Command("balance"))
@router.message(F.text == "💳 Баланс")
async def btn_balance(message: Message) -> None:
    if await is_banned(message.from_user.id):
        return
    await _send_balance(message, message.from_user.id)


# ============================================================
# 💳 /buy — пополнение
# ============================================================

async def _send_buy(message: Message, uid: int) -> None:
    from keyboards.main import balance_inline
    bal = await db.get_balance(uid)
    mode = await db.get_billing_mode()

    text = (
        "💳 <b>Пополнение баланса</b>\n\n"
        f"💰 Текущий баланс: <b>{bal}⭐</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Как использовать баланс:</b>\n"
        "  • Скачивание трека: 5⭐\n"
        "  • Распознавание: 3⭐\n"
        "  • Скачивание плейлиста: 20⭐\n\n"
        "🎁 <b>Бонус:</b> повторные скачивания — <b>бесплатно</b> (кэш)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <b>Выбери пакет пополнения:</b>\n"
        "Оплата через <b>Telegram Stars</b> — картой или звёздами"
    )

    if mode.get("subscription_enabled"):
        text += "\n\n💎 <i>Выгоднее:</i> подписка /sub — безлимит"
    if bal > 0:
        text += f"\n\n✅ У тебя уже есть <b>{bal}⭐</b> на балансе."

    try:
        await message.edit_text(text, reply_markup=balance_inline())
    except Exception:
        await message.answer(text, reply_markup=balance_inline())

@router.message(Command("buy"))
async def cmd_buy(message: Message) -> None:
    if await is_banned(message.from_user.id):
        return
    await _send_buy(message, message.from_user.id)


@router.callback_query(F.data == "user:buy")
async def cb_buy(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:
        pass
    await _send_buy(call.message, call.from_user.id)
    await call.answer()


# ============================================================
# 🎁 ТРИАЛ
# ============================================================

async def _send_trial_result(message: Message, uid: int, edit: bool = False):
    trial = await db.get_trial()
    if not trial.get("enabled"):
        await message.answer(
            "🎁 <b>Триал недоступен</b>\n\n"
            "💡 Варианты:\n"
            "  • 💎 Подписка: /sub\n"
            "  • 💳 Баланс: /buy",
            reply_markup=cancel_kb(),
        )
        return
    if await db.is_paid(uid):
        user = await db.get_user(uid)
        sub_end = "?"
        if user and user.get("subscription_end"):
            sub_end = user["subscription_end"].strftime("%d.%m.%Y")
        await message.answer(
            f"✅ <b>Подписка уже активна</b>\n\n"
            f"До: <b>{sub_end}</b>\n\n"
            f"💡 Триал — только для новых.",
            reply_markup=cancel_kb(),
        )
        return
    user = await db.get_user(uid)
    if user and user.get("trial_used"):
        await message.answer(
            "❌ <b>Триал уже использован</b>\n\n"
            "Каждый юзер — <b>один раз</b>.\n\n"
            "💡 /sub или /buy",
            reply_markup=cancel_kb(),
        )
        return
    ok = await db.activate_trial(uid)
    if ok:
        days = trial["days"]
        result_text = (
            f"🎉 <b>Триал активирован!</b>\n\n"
            f"✅ <b>{days} дн.</b> безлимита\n\n"
            f"<b>Что доступно:</b>\n"
            f"  • 🎵 Скачивать треки\n"
            f"  • 🎤 Распознавать\n"
            f"  • 📋 Плейлисты\n\n"
            f"Просто пришли ссылку или нажми 🎵"
        )
        if edit:
            try:
                await message.edit_text(result_text)
                return
            except Exception:
                pass
        await message.answer(result_text)
    else:
        msg = "❌ Не удалось. Попробуй позже."
        if edit:
            try:
                await message.edit_text(msg, reply_markup=cancel_kb())
                return
            except Exception:
                pass
        await message.answer(msg, reply_markup=cancel_kb())


@router.message(Command("trial"))
@router.message(F.text == "🎁 Триал")
async def btn_trial(message: Message) -> None:
    if await is_banned(message.from_user.id):
        return
    await _send_trial_result(message, message.from_user.id)


@router.callback_query(F.data == "user:trial")
async def cb_trial(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:
        pass
    await _send_trial_result(call.message, call.from_user.id)
    await call.answer()


# ============================================================
# 💡 КАК РАБОТАЕТ
# ============================================================

@router.message(F.text == "💡 Как работает")
async def btn_howto(message: Message) -> None:
    text = (
        "💡 <b>Как пользоваться</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎵 <b>1. Скачать трек</b>\n\n"
        "Пришли ссылку из:\n"
        "  • Spotify\n"
        "  • SoundCloud\n"
        "  • YouTube\n"
        "  • Яндекс.Музыка\n"
        "  • Bandcamp, VK, Mixcloud\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎤 <b>2. Распознать</b>\n\n"
        "Голосовое 10-15 сек → ищу в Shazam\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>3. Плейлист</b>\n\n"
        "Ссылка на альбом/плейлист → до 20 треков\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📝 <b>4. Текст песни</b>\n\n"
        "/lyrics Исполнитель - Название\n"
        "или /lyrics после скачивания\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 <b>Оплата</b>\n\n"
        "• Подписка /sub — безлимит\n"
        "• Баланс /buy — за действия\n"
        "• Триал /trial — один раз\n\n"
        "💡 <b>Кэш</b> — повторно бесплатно"
    )
    await message.answer(text, reply_markup=cancel_kb())


# ============================================================
# ❓ ПОМОЩЬ
# ============================================================

@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def btn_help(message: Message) -> None:
    text = (
        "❓ <b>Помощь</b>\n\n"
        "Выбери раздел:"
    )
    await message.answer(text, reply_markup=help_inline())


@router.callback_query(F.data == "user:help")
async def cb_help_main(call: CallbackQuery) -> None:
    try:
        await call.message.edit_text("❓ <b>Помощь</b>\n\nВыбери раздел:", reply_markup=help_inline())
    except Exception:
        await call.message.answer("❓ <b>Помощь</b>", reply_markup=help_inline())
    await call.answer()


@router.callback_query(F.data == "user:help_download")
async def cb_help_download(call: CallbackQuery) -> None:
    text = (
        "🎵 <b>Как скачать трек</b>\n\n"
        "<b>1. Скопируй ссылку</b> из приложения:\n\n"
        "• Spotify — «Поделиться» → «Скопировать ссылку»\n"
        "• SoundCloud — «Share» → «Copy link»\n"
        "• YouTube — «Поделиться» → «Скопировать»\n"
        "• Яндекс.Музыка — «Поделиться» → «Скопировать»\n\n"
        "<b>2. Отправь в чат</b> — просто вставь\n\n"
        "<b>3. Жди</b> — 10-30 сек\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Примеры:</b>\n"
        "<code>open.spotify.com/track/...</code>\n"
        "<code>soundcloud.com/artist/track</code>\n"
        "<code>youtu.be/dQw4w9WgXcQ</code>\n"
        "<code>music.yandex.ru/album/.../track/...</code>\n\n"
        "💡 Плейлисты тоже работают"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:help_recognize")
async def cb_help_recognize(call: CallbackQuery) -> None:
    text = (
        "🎤 <b>Как распознать</b>\n\n"
        "<b>Когда:</b> услышал где-то, не знаешь название\n\n"
        "<b>Как:</b>\n"
        "1. Запиши голосовое 10-15 сек\n"
        "2. Отправь в чат\n"
        "3. Жди результат\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Советы:</b>\n"
        "  • Минимум 10 сек\n"
        "  • Ближе к колонке\n"
        "  • Слышны слова — лучше\n\n"
        "💳 <b>Не нашёл — не списывается</b>"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:help_billing")
async def cb_help_billing(call: CallbackQuery) -> None:
    text = (
        "💎 <b>Подписка vs Баланс</b>\n\n"
        "<b>💎 Подписка</b>\n"
        "• Безлимит на всё\n"
        "• Выгодно если часто качаешь\n"
        "• /sub\n\n"
        "<b>💳 Баланс</b>\n"
        "• За каждое действие\n"
        "• Кэш бесплатно\n"
        "• /buy\n\n"
        "<b>🎁 Триал</b>\n"
        "• Бесплатно один раз\n"
        "• /trial\n\n"
        "💡 Мой совет: качаешь >2/день — подписка"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:help_buy")
async def cb_help_buy(call: CallbackQuery) -> None:
    text = (
        "💳 <b>Как пополнить</b>\n\n"
        "<b>Сейчас:</b>\n"
        "Напиши @admin — зачислит на баланс\n\n"
        "<b>Скоро:</b>\n"
        "Telegram Stars прямо в боте\n\n"
        "💡 <b>Выгоднее подписка:</b> /sub"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:help_troubleshoot")
async def cb_help_trouble(call: CallbackQuery) -> None:
    text = (
        "🆘 <b>Проблемы</b>\n\n"
        "<b>Ссылка не принимается</b>\n"
        "• Полная с https://\n"
        "• Из «Поделиться»\n\n"
        "<b>Не скачивается</b>\n"
        "• Ремикс может не быть на YouTube\n"
        "• Приватный плейлист\n\n"
        "<b>Не распознаёт</b>\n"
        "• Минимум 10 сек\n"
        "• Громче звук\n\n"
        "<b>Совсем не работает</b>\n"
        "Напиши @admin"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:hint_download")
async def cb_hint_download(call: CallbackQuery) -> None:
    await call.message.answer(
        "🎵 Пришли ссылку:\n\n"
        "<b>Spotify · SoundCloud · YouTube · Яндекс · Bandcamp · VK · Mixcloud</b>\n\n"
        "Или 🎤 для распознавания.",
        reply_markup=cancel_kb(),
    )
    await call.answer()


# ============================================================
# 📝 ТЕКСТ ПЕСНИ
# ============================================================

@router.message(Command("lyrics"))
async def cmd_lyrics(message: Message) -> None:
    if await is_banned(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        await _do_lyrics(message, parts[1].strip())
        return
    tracks = await db.get_user_downloads(message.from_user.id, limit=1)
    if tracks and tracks[0].get("title"):
        t = tracks[0]
        await _do_lyrics(message, f"{t.get('performer','')} - {t['title']}")
    else:
        await message.answer(
            "📝 <b>Текст песни</b>\n\n"
            "Использование: <code>/lyrics Исполнитель - Название</code>\n\n"
            "Или после скачивания: /lyrics без аргументов",
            reply_markup=cancel_kb(),
        )


@router.message(F.text == "📝 Текст песни")
async def btn_lyrics(message: Message, state: FSMContext) -> None:
    if await is_banned(message.from_user.id):
        return
    from states import UserLyricsStates
    await state.set_state(UserLyricsStates.waiting_query)
    await message.answer(
        "📝 <b>Текст песни</b>\n\n"
        "Напиши: <code>Исполнитель - Название</code>\n\n"
        "Например: <code>Imagine Dragons - Believer</code>\n\n"
        "💡 Или ссылку: /lyrics URL\n"
        "💡 Или /lyrics после скачивания\n\n"
        "🔴 <b>Жду запрос...</b>",
        reply_markup=cancel_kb(),
    )


@router.message(UserLyricsStates.waiting_query)
async def msg_lyrics_query(message: Message, state: FSMContext) -> None:
    await state.clear()
    query = (message.text or "").strip()
    if not query or query == "/cancel":
        await message.answer("❌ Отменено.")
        return
    if len(query) < 3:
        await message.answer("⚠️ Слишком коротко. Напиши: Исполнитель - Название")
        return
    await _do_lyrics(message, query)


async def _do_lyrics(message: Message, query: str) -> None:
    from services.lyrics import clean_lyrics, extract_meta_from_url, fetch_lyrics

    artist, title = "", query

    if query.startswith("http://") or query.startswith("https://"):
        status = await message.answer("🔗 Извлекаю из ссылки...")
        try:
            meta = await extract_meta_from_url(query)
        except Exception as e:
            try:
                await status.edit_text(f"❌ Ошибка: {e}")
            except Exception:
                pass
            return
        if not meta or not meta[1]:
            try:
                await status.edit_text(
                    "❌ Не удалось извлечь.\n\n"
                    "Пришли: <code>/lyrics Исполнитель - Название</code>"
                )
            except Exception:
                pass
            return
        artist, title = meta
        try:
            await status.delete()
        except Exception:
            pass
    else:
        for sep in [" - ", " – ", " — ", ", "]:
            if sep in query:
                artist, title = [p.strip() for p in query.split(sep, 1)]
                break

    if not title:
        await message.answer("⚠️ Используй: <code>Исполнитель - Название</code>", reply_markup=cancel_kb())
        return

    status = await message.answer("🔎 Ищу текст...")
    try:
        r = await fetch_lyrics(artist, title)
    except Exception as e:
        try:
            await status.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            pass
        return

    if not r:
        try:
            await status.edit_text(
                f"❌ <b>Не найдено</b>\n\n"
                f"<i>{html.escape(artist or '—')} — {html.escape(title)}</i>\n\n"
                "💡 Проверь написание"
            )
        except Exception:
            pass
        return

    text = clean_lyrics(r["lyrics"])
    header = f"📝 <b>{html.escape(artist or '—')} — {html.escape(title)}</b>\n<i>{r['source']}</i>\n\n"
    body = html.escape(text)

    if len(header) + len(body) <= 4096:
        try:
            await status.edit_text(header + body)
        except Exception as e:
            try:
                await status.edit_text(f"❌ {e}")
            except Exception:
                pass
        return

    try:
        await status.delete()
    except Exception:
        pass
    await message.answer(header + "<i>(частями)</i>")
    chunk = 3800
    rest = body
    while rest:
        cut = rest.rfind("\n\n", 0, chunk)
        if cut < 1000:
            cut = chunk
        await message.answer(rest[:cut])
        rest = rest[cut:].lstrip("\n")

# ============================================================
# 🏠 ГЛАВНОЕ МЕНЮ (инлайн)
# ============================================================

@router.message(F.text == "🏠 Меню")
@router.message(Command("menu"))
async def btn_main_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    if await is_banned(message.from_user.id):
        return
    admin = await is_admin(message.from_user.id)
    await message.answer(
        "🏠 <b>Главное меню</b>\n\n"
        "Выбери действие:",
        reply_markup=main_inline(is_admin=admin),
    )


@router.callback_query(F.data == "user:menu")
async def cb_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if await is_banned(call.from_user.id):
        return
    admin = await is_admin(call.from_user.id)
    try:
        await call.message.edit_text(
            "🏠 <b>Главное меню</b>\n\nВыбери действие:",
            reply_markup=main_inline(is_admin=admin),
        )
    except Exception:
        await call.message.answer(
            "🏠 <b>Главное меню</b>",
            reply_markup=main_inline(is_admin=admin),
        )
    await call.answer()


@router.callback_query(F.data == "user:menu_download")
async def cb_menu_download(call: CallbackQuery) -> None:
    text = (
        "🎵 <b>Скачать трек</b>\n\n"
        "Пришли ссылку из:\n\n"
        "• <b>Spotify</b> — open.spotify.com/track/...\n"
        "• <b>SoundCloud</b> — soundcloud.com/artist/track\n"
        "• <b>YouTube</b> — youtu.be/...\n"
        "• <b>Яндекс.Музыка</b> — music.yandex.ru/album/.../track/...\n"
        "• <b>Bandcamp, VK, Mixcloud</b>\n\n"
        "💡 Просто скопируй из «Поделиться» и пришли сюда."
    )
    try:
        await call.message.edit_text(text, reply_markup=cancel_kb())
    except Exception:
        await call.message.answer(text, reply_markup=cancel_kb())
    await call.answer()


@router.callback_query(F.data == "user:menu_recognize")
async def cb_menu_recognize(call: CallbackQuery, state: FSMContext) -> None:
    from states import RecognizeStates
    await state.set_state(RecognizeStates.waiting_voice)
    text = (
        "🎤 <b>Распознать музыку</b>\n\n"
        "🔴 <b>Жду голосовое сообщение</b>\n\n"
        "Запиши фрагмент 10-15 секунд и отправь сюда.\n\n"
        "💡 Советы:\n"
        "  • Минимум 10 секунд\n"
        "  • Ближе к источнику звука\n\n"
        "💳 <i>Если не распознаю — деньги не спишутся</i>"
    )
    try:
        await call.message.edit_text(text, reply_markup=recognize_kb())
    except Exception:
        await call.message.answer(text, reply_markup=recognize_kb())
    await call.answer()


@router.callback_query(F.data == "user:menu_playlist")
async def cb_menu_playlist(call: CallbackQuery) -> None:
    text = (
        "📋 <b>Скачать плейлист</b>\n\n"
        "Пришли ссылку на <b>альбом или плейлист</b>:\n\n"
        "• <b>Spotify</b> — open.spotify.com/album/... или /playlist/...\n"
        "• <b>Яндекс.Музыка</b> — music.yandex.ru/album/...\n"
        "• <b>SoundCloud</b> — soundcloud.com/artist/sets/...\n"
        "• <b>YouTube</b> — youtube.com/playlist?list=...\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Максимум <b>20 треков</b> за раз\n"
        "💡 Работает через Deezer — находит похожий альбом по названию"
    )
    try:
        await call.message.edit_text(text, reply_markup=cancel_kb())
    except Exception:
        await call.message.answer(text, reply_markup=cancel_kb())
    await call.answer()


@router.callback_query(F.data == "user:menu_lyrics")
async def cb_menu_lyrics(call: CallbackQuery, state: FSMContext) -> None:
    from states import UserLyricsStates
    await state.set_state(UserLyricsStates.waiting_query)
    text = (
        "📝 <b>Текст песни</b>\n\n"
        "Напиши: <code>Исполнитель - Название</code>\n\n"
        "Например: <code>Imagine Dragons - Believer</code>\n\n"
        "💡 Или ссылку на трек"
    )
    try:
        await call.message.edit_text(text, reply_markup=cancel_kb())
    except Exception:
        await call.message.answer(text, reply_markup=cancel_kb())
    await call.answer()


@router.callback_query(F.data == "user:menu_profile")
async def cb_menu_profile(call: CallbackQuery) -> None:
    from handlers.start import _send_profile
    await _send_profile(call.message, call.from_user.id, edit=True)
    await call.answer()


@router.callback_query(F.data == "user:menu_sub")
async def cb_menu_sub(call: CallbackQuery) -> None:
    await _send_sub(call.message, call.from_user.id, edit=True)
    await call.answer()


@router.callback_query(F.data == "user:menu_balance")
async def cb_menu_balance(call: CallbackQuery) -> None:
    await _send_balance(call.message, call.from_user.id, edit=True)
    await call.answer()


@router.callback_query(F.data == "user:menu_trial")
async def cb_menu_trial(call: CallbackQuery) -> None:
    await _send_trial_result(call.message, call.from_user.id, edit=True)
    await call.answer()


@router.callback_query(F.data == "user:menu_howto")
async def cb_menu_howto(call: CallbackQuery) -> None:
    text = (
        "💡 <b>Как пользоваться</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎵 <b>Скачать трек</b>\n"
        "Пришли ссылку из Spotify / SoundCloud / YouTube / Яндекс\n\n"
        "🎤 <b>Распознать</b>\n"
        "Голосовое 10-15 сек\n\n"
        "📋 <b>Плейлист</b>\n"
        "Ссылка на альбом — до 20 треков\n\n"
        "📝 <b>Текст песни</b>\n"
        "/lyrics Исполнитель - Название\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 <b>Оплата</b>\n"
        "• /sub — подписка (безлимит)\n"
        "• /buy — баланс (за действия)\n"
        "• /trial — триал (один раз)\n\n"
        "💡 Кэш: повторный трек — бесплатно"
    )
    try:
        await call.message.edit_text(text, reply_markup=cancel_kb())
    except Exception:
        await call.message.answer(text, reply_markup=cancel_kb())
    await call.answer()