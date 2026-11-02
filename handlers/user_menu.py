import html
import logging

import config
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import postgres_db as db
from states import UserLyricsStates
from keyboards.main import (
    back_to_help,
    help_inline,
    lyrics_cancel_kb,
    sub_inline,
    tracks_inline,
)
from utils.checks import is_banned

router = Router(name="user_menu")
async def _price_lines(uid: int) -> str:
    """Показывает цены только если PPU реально основной режим."""
    import config as _cfg
    paid = await db.is_paid(uid)
    if _cfg.FREE_MODE:
        return "💎 <b>У тебя безлимит</b> (free_mode)\n"
    if paid:
        return "💎 <b>У тебя активна подписка — безлимит</b>\n"
    mode = await db.get_billing_mode()
    if mode.get("subscription_enabled") and not mode.get("pay_per_use_enabled"):
        return "💎 <b>Оформи подписку /sub</b> — безлимит\n"
    if mode.get("subscription_enabled") and mode.get("pay_per_use_enabled"):
        # Оба режима — показываем что можно так или так
        prices = await db.get_action_prices()
        lines = "💡 <b>Два варианта:</b>\n"
        lines += "  💎 Подписка /sub — безлимит\n"
        lines += "  💳 Или за действие:\n"
        for k, t in _cfg.ACTION_KEYS.items():
            lines += f"     • {t}: {prices.get(k, 0)}⭐\n"
        return lines
    # Только PPU
    prices = await db.get_action_prices()
    lines = "📋 <b>Цены за действие:</b>\n"
    for k, t in _cfg.ACTION_KEYS.items():
        lines += f"  • {t}: {prices.get(k, 0)}⭐\n"
    return lines
logger = logging.getLogger(__name__)


def _e(v):
    return html.escape(str(v)) if v is not None else "—"


async def _lang(user_id: int) -> str:
    try:
        user = await db.get_user(user_id)
        return (user or {}).get("lang") or "ru"
    except Exception:
        return "ru"


# ============================================================
# 📜 МОИ ТРЕКИ
# ============================================================

@router.message(F.text == "📜 Мои треки")
async def btn_my_tracks(message: Message) -> None:
    uid = message.from_user.id
    if await is_banned(uid):
        return
    tracks = await db.get_user_downloads(uid, limit=10)
    total = await db.count_user_downloads(uid)

    if not tracks:
        text = (
            "📜 <b>Мои треки</b>\n\n"
            "Ты пока ничего не скачивал.\n\n"
            "💡 <b>Как начать:</b>\n"
            "• Пришли ссылку на трек (Spotify, SoundCloud, YouTube, Яндекс)\n"
            "• Или нажми <b>🎵 Скачать трек</b> в меню\n"
            "• Или <b>🎤 Распознать</b> — если услышал где-то"
        )
        await message.answer(text, reply_markup=tracks_inline(False))
        return

    text = (
        f"📜 <b>Мои треки</b>\n\n"
        f"Всего скачано: <b>{total}</b>\n"
        f"Последние {len(tracks)}:\n\n"
    )
    for i, t in enumerate(tracks, 1):
        title = _e(t['title'] or '?')[:50]
        artist = _e(t['performer'] or '?')[:40]
        plat = t['platform'] or '?'
        date = t['downloaded_at'].strftime('%d.%m %H:%M') if t['downloaded_at'] else '?'
        text += f"{i}. <b>{artist}</b> — {title}\n"
        text += f"   <code>{plat}</code> · {date}\n"
    text += "\n💡 Кэш: повторная отправка той же ссылки — <b>бесплатно</b>"
    await message.answer(text, reply_markup=tracks_inline(True))


@router.callback_query(F.data == "user:tracks_refresh")
async def cb_tracks_refresh(call: CallbackQuery) -> None:
    await call.message.delete()
    fake_msg = call.message
    fake_msg.from_user = call.from_user
    await btn_my_tracks(fake_msg)
    await call.answer()


# ============================================================
# 💎 ПОДПИСКА
# ============================================================

@router.message(Command("sub"))
@router.message(F.text == "💎 Подписка")
async def btn_sub(message: Message) -> None:
    uid = message.from_user.id
    if await is_banned(uid):
        return
    pricing = await db.get_pricing()
    mode = await db.get_billing_mode()
    paid = await db.is_paid(uid)
    balance = await db.get_balance(uid)

    sub_end = "—"
    if paid:
        user = await db.get_user(uid)
        if user and user.get("subscription_end"):
            sub_end = user["subscription_end"].strftime("%d.%m.%Y")

    text = (
        "💎 <b>Подписка Premium</b>\n\n"
    )
    if paid:
        text += f"✅ <b>У тебя активна</b> до <b>{sub_end}</b>\n\n"
    else:
        text += f"🆓 Текущий статус: <b>бесплатный</b>\n"
        text += f"💳 Баланс: <b>{balance}⭐</b>\n\n"

    if mode.get("subscription_enabled"):
        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        text += "<b>Что даёт подписка:</b>\n"
        text += "  ✅ Безлимит на скачивания\n"
        text += "  ✅ Безлимит на распознавание\n"
        text += "  ✅ Безлимит на плейлисты\n"
        text += "  ✅ Не нужно платить за каждое действие\n\n"
        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        text += "<b>Тарифы:</b>\n"
        for key in ["7", "30", "90"]:
            if key in pricing:
                info = pricing[key]
                per_day = round(info["stars"] / info["days"], 1)
                text += f"  💎 {info['days']} дней — <b>{info['stars']}⭐</b> ({per_day}⭐/день)\n"
        text += "\n💡 <b>7д</b> — попробовать, <b>30д</b> — стандарт, <b>90д</b> — выгодно\n"
        if not paid:
            text += "\n⚠️ <i>Покупка через Stars — скоро. Пока напиши /buy</i>"
        kb = sub_inline(pricing, True)
    else:
        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        text += "⚠️ <b>Подписка временно отключена админом</b>\n\n"
        text += "Сейчас работает <b>оплата за действие</b>:\n"
        prices = await db.get_action_prices()
        for key, title in config.ACTION_KEYS.items():
            text += f"  • {title}: {prices.get(key, 0)}⭐\n"
        text += "\n💡 Пополни баланс: /buy"
        kb = sub_inline(pricing, False)

    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("user:sub:"))
async def cb_sub_buy(call: CallbackQuery) -> None:
    plan_key = call.data.split(":")[-1]
    pricing = await db.get_pricing()
    info = pricing.get(plan_key)
    if not info:
        await call.answer("Тариф недоступен", show_alert=True)
        return
    await call.answer(
        f"Оплата подписки на {info['days']} дней скоро появится.\n\n"
        f"Пока напиши админу — он выдаст вручную.",
        show_alert=True,
    )


# ============================================================
# 💳 БАЛАНС
# ============================================================

@router.message(Command("balance"))
@router.message(F.text == "💳 Баланс")
async def btn_balance(message: Message) -> None:
    uid = message.from_user.id
    if await is_banned(uid):
        return
    bal = await db.get_balance(uid)
    prices = await db.get_action_prices()
    txs = await db.get_transactions(uid, limit=10)
    mode = await db.get_billing_mode()
    free_limit = int(mode.get("free_actions_per_day", 0))
    free_used = await db.get_total_free_actions_used(uid)

    text = "💳 <b>Баланс</b>\n\n"
    text += f"💰 Текущий: <b>{bal}⭐</b>\n"
    if free_limit > 0:
        text += f"🎁 Бесплатных сегодня: <b>{max(0, free_limit - free_used)}/{free_limit}</b>\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    text += await _price_lines(uid)
    text += "\n💡 <b>Кэш бесплатно:</b> повторная отправка ссылки не списывает ⭐\n"
    if txs:
        text += "\n━━━━━━━━━━━━━━━━━━━━━\n"
        text += "<b>Последние операции:</b>\n"
        for tx in txs:
            sign = "+" if tx["amount"] > 0 else ""
            kind_emoji = {"topup": "➕", "charge": "💳", "manual": "✏️"}.get(tx["kind"], "•")
            act = f" · {tx['action']}" if tx["action"] else ""
            text += f"  {kind_emoji} {sign}{tx['amount']}⭐{act}\n"
    text += "\n\n💡 Пополнить: /buy\n💎 Или подписка безлимит: /sub"
    await message.answer(text, reply_markup=cancel_kb())


# ============================================================
# 💳 /buy — пополнение
# ============================================================

@router.message(Command("buy"))
@router.callback_query(F.data == "user:buy")
async def btn_buy(target) -> None:
    if isinstance(target, CallbackQuery):
        message = target.message
        message.from_user = target.from_user
        await target.answer()
    else:
        message = target
    uid = message.from_user.id
    if await is_banned(uid):
        return
    bal = await db.get_balance(uid)
    prices = await db.get_action_prices()

    text = (
        "💳 <b>Пополнение баланса</b>\n\n"
        f"💰 Текущий: <b>{bal}⭐</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Как пополнить:</b>\n\n"
        "🔹 <b>Сейчас (через админа):</b>\n"
        "  Напиши @admin — он зачислит на баланс\n\n"
        "🔹 <b>Скоро (Telegram Stars):</b>\n"
        "  Прямая оплата картой или звёздами в боте\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Зачем нужен баланс:</b>\n"
        "  • Скачивание — списывается за трек\n"
        "  • Распознавание — списывается за попытку\n"
        "  • Плейлист — списывается за загрузку\n\n"
        "💡 <b>Хитрость:</b> повторные скачивания <b>бесплатно</b> (кэш)\n\n"
        "💎 <b>Выгодно:</b> подписка /sub — безлимит\n"
    )
    text += "\n<b>Цены:</b>\n"
    for key, title in config.ACTION_KEYS.items():
        text += f"  • {title}: {prices.get(key, 0)}⭐\n"
    await message.answer(text, reply_markup=cancel_kb())


# ============================================================
# 🎁 ТРИАЛ
# ============================================================

@router.message(Command("trial"))
@router.message(F.text == "🎁 Триал")
async def btn_trial(message: Message) -> None:
    uid = message.from_user.id
    if await is_banned(uid):
        return
    trial = await db.get_trial()
    if not trial.get("enabled"):
        await message.answer(
            "🎁 <b>Триал недоступен</b>\n\n"
            "Админ отключил пробный период.\n\n"
            "💡 Варианты:\n"
            "• 💎 Подписка: /sub\n"
            "• 💳 Пополнить баланс: /buy"
        )
        return
    if await db.is_paid(uid):
        user = await db.get_user(uid)
        sub_end = "?"
        if user and user.get("subscription_end"):
            sub_end = user["subscription_end"].strftime("%d.%m.%Y")
        await message.answer(
            f"✅ <b>У тебя уже активна подписка</b>\n\n"
            f"Действует до: <b>{sub_end}</b>\n\n"
            f"💡 Триал — только для новых пользователей."
        )
        return
    user = await db.get_user(uid)
    if user and user.get("trial_used"):
        await message.answer(
            "❌ <b>Триал уже использован</b>\n\n"
            "Каждый пользователь может активировать триал <b>один раз</b>.\n\n"
            "💡 Что можно:\n"
            "• 💎 Оформить подписку: /sub\n"
            "• 💳 Пополнить баланс: /buy\n"
            "• 🎁 Попросить триал у админа — он может сбросить"
        )
        return
    ok = await db.activate_trial(uid)
    if ok:
        days = trial["days"]
        await message.answer(
            f"🎉 <b>Триал активирован!</b>\n\n"
            f"✅ Тебе начислено <b>{days} дн.</b> безлимита\n\n"
            f"<b>Что теперь доступно:</b>\n"
            f"  • 🎵 Скачивать треки — без ограничений\n"
            f"  • 🎤 Распознавать — без ограничений\n"
            f"  • 📜 Плейлисты — без ограничений\n\n"
            f"<b>Как пользоваться:</b>\n"
            f"  Просто пришли ссылку на трек или нажми 🎵\n\n"
            f"💡 После окончания — оформить /sub или пополнить /buy"
        )
    else:
        await message.answer("❌ Не удалось активировать. Попробуй позже.")


# ============================================================
# 💡 КАК ЭТО РАБОТАЕТ
# ============================================================

@router.message(F.text == "💡 Как работает")
async def btn_howto(message: Message) -> None:
    text = (
        "💡 <b>Как пользоваться ботом</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎵 <b>1. Скачать трек</b>\n\n"
        "Скопируй ссылку из приложения и пришли в бот:\n\n"
        "<b>Spotify:</b>\n"
        "  <code>open.spotify.com/track/...</code>\n"
        "  <code>open.spotify.com/album/...</code>\n"
        "  <code>open.spotify.com/playlist/...</code>\n\n"
        "<b>SoundCloud:</b>\n"
        "  <code>soundcloud.com/artist/track</code>\n"
        "  <code>soundcloud.com/artist/sets/...</code>\n\n"
        "<b>YouTube:</b>\n"
        "  <code>youtube.com/watch?v=...</code>\n"
        "  <code>youtu.be/...</code>\n\n"
        "<b>Яндекс.Музыка:</b>\n"
        "  <code>music.yandex.ru/album/.../track/...</code>\n\n"
        "<b>Bandcamp, VK Музыка, Mixcloud</b> — тоже работают\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎤 <b>2. Распознать музыку</b>\n\n"
        "Услышал трек где-то? Запиши 10-15 сек фрагмент\n"
        "и отправь боту как <b>голосовое</b> или <b>аудио</b>.\n\n"
        "Бот найдёт название и скачает трек.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📜 <b>3. Мои треки</b>\n\n"
        "Все скачанные треки сохраняются.\n"
        "Можно посмотреть последние 10 и вспомнить что искал.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 <b>4. Оплата</b>\n\n"
        "<b>Вариант 1 — Подписка (безлимит):</b>\n"
        "  7/30/90 дней, качаешь сколько хочешь\n"
        "  Смотреть тарифы: /sub\n\n"
        "<b>Вариант 2 — Баланс (за действие):</b>\n"
        "  Пополняешь ⭐, списывается цена за трек\n"
        "  Баланс: /balance, Пополнить: /buy\n\n"
        "<b>Вариант 3 — Триал (бесплатно):</b>\n"
        "  Один раз активировать /trial\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Хитрости</b>\n\n"
        "• <b>Кэш бесплатно</b> — если этот трек уже скачивал, повторно не списывается\n"
        "• <b>Плейлисты</b> — можно кинуть ссылку на плейлист\n"
        "• <b>Качество</b> — 320 kbps mp3 с обложкой и тегами"
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
        "Выбери раздел для подробностей:\n\n"
        "🎵 <b>Как скачать</b> — примеры ссылок\n"
        "🎤 <b>Как распознать</b> — про голосовые\n"
        "💎 <b>Подписка vs Баланс</b> — что выбрать\n"
        "💳 <b>Как пополнить</b> — способы оплаты\n"
        "🆘 <b>Проблемы</b> — если что-то не работает\n\n"
        "💡 Или команды:\n"
        "  /sub — подписка\n"
        "  /balance — баланс\n"
        "  /buy — пополнить\n"
        "  /trial — активировать триал"
    )
    await message.answer(text, reply_markup=help_inline())


@router.callback_query(F.data == "user:help")
async def cb_help_main(call: CallbackQuery) -> None:
    text = (
        "❓ <b>Помощь</b>\n\n"
        "Выбери раздел:"
    )
    try:
        await call.message.edit_text(text, reply_markup=help_inline())
    except Exception:
        await call.message.answer(text, reply_markup=help_inline())
    await call.answer()


@router.callback_query(F.data == "user:help_download")
async def cb_help_download(call: CallbackQuery) -> None:
    text = (
        "🎵 <b>Как скачать трек</b>\n\n"
        "<b>1. Скопируй ссылку</b> из приложения:\n\n"
        "• Spotify — «Поделиться» → «Копировать ссылку на трек»\n"
        "• SoundCloud — «Share» → «Copy link»\n"
        "• YouTube — «Поделиться» → «Скопировать»\n"
        "• Яндекс.Музыка — «Поделиться» → «Скопировать ссылку»\n\n"
        "<b>2. Отправь сюда</b> — просто вставь в чат\n\n"
        "<b>3. Жди</b> — 10-30 сек, придёт mp3\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Примеры правильных ссылок:</b>\n\n"
        "<code>https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT</code>\n"
        "<code>https://soundcloud.com/octobersveryown/drake-hotline-bling</code>\n"
        "<code>https://youtu.be/dQw4w9WgXcQ</code>\n"
        "<code>https://music.yandex.ru/album/12345/track/67890</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Советы:</b>\n"
        "• Плейлисты и альбомы тоже работают\n"
        "• Не работает Spotify → попробуй найти трек на SoundCloud\n"
        "• Редкие треки могут не найтись на YouTube — придёт сообщение"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:help_recognize")
async def cb_help_recognize(call: CallbackQuery) -> None:
    text = (
        "🎤 <b>Как распознать музыку</b>\n\n"
        "<b>Когда использовать:</b>\n"
        "Услышал трек в кафе/на улице/в видео — не знаешь название\n\n"
        "<b>Как:</b>\n"
        "1. Запиши <b>голосовое сообщение</b> 10-15 сек\n"
        "   (отправь боту в чат)\n"
        "2. Бот слушает, ищет в Shazam\n"
        "3. Если нашёл — скачивает и присылает mp3\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Советы:</b>\n"
        "• <b>10-15 сек</b> — оптимально\n"
        "• Тихо? Попробуй ближе к колонке\n"
        "• Слышно слова? Лучше\n"
        "• Можно отправить <b>аудио</b> файл или <b>видео</b>\n"
        "• Ремиксы Shazam часто не знает — это нормально\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💳 <b>Стоимость:</b>\n"
        "• В подписке — бесплатно\n"
        "• По балансу — списывается цена /balance\n"
        "• Не нашёл — <b>не списывается</b>"
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
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>💎 Подписка</b>\n\n"
        "• Фиксированная цена за период (7/30/90 дней)\n"
        "• <b>Безлимит</b> на всё\n"
        "• Выгодно если качаешь часто\n"
        "• Пример: 30 дней за 299⭐\n"
        "• Окупается за ~60 треков\n\n"
        "Оформить: /sub\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>💳 Баланс (по действиям)</b>\n\n"
        "• Пополняешь ⭐, тратишь по мере надобности\n"
        "• Платишь за каждый трек (например 5⭐)\n"
        "• Выгодно если качаешь редко\n"
        "• <b>Кэш бесплатно</b> — повторный трек не списывается\n\n"
        "Пополнить: /buy · Баланс: /balance\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>🎁 Триал</b>\n\n"
        "Один раз можно активировать бесплатный период.\n"
        "Активировать: /trial\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Мой совет:</b>\n"
        "Качаешь больше 2 треков в день? Подписка выгоднее.\n"
        "Раз в неделю? Баланс."
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:help_buy")
async def cb_help_buy(call: CallbackQuery) -> None:
    text = (
        "💳 <b>Как пополнить баланс</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Сейчас (вручную):</b>\n\n"
        "Напиши админу <b>@admin</b> и попроси пополнить.\n"
        "Скажи сколько ⭐ нужно и зачем.\n\n"
        "<b>Способы оплаты админу:</b>\n"
        "• Перевод по номеру карты\n"
        "• Telegram Stars\n"
        "• Криптовалюта\n"
        "• Любой удобный\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Скоро:</b>\n\n"
        "Прямая оплата <b>Telegram Stars</b> в боте.\n"
        "Нажмёшь кнопку → заплатил → баланс пополнился.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Курс:</b>\n\n"
        "1⭐ ≈ 0.013$\n"
        "100⭐ ≈ 1.30$\n\n"
        "Точный курс при оплате.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Выгоднее подписка:</b>\n"
        "Если планируешь много качать — оформи /sub"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:help_troubleshoot")
async def cb_help_trouble(call: CallbackQuery) -> None:
    text = (
        "🆘 <b>Если что-то не работает</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>❌ Ссылка не принимается</b>\n\n"
        "• Проверь что это <b>полная ссылка</b> с https://\n"
        "• Скопируй из «Поделиться» приложения, не из адресной строки\n"
        "• Проверь платформу — поддерживаются Spotify, SoundCloud, YouTube, Яндекс, Bandcamp, VK, Mixcloud\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>❌ Трек не скачивается</b>\n\n"
        "• Редкий ремикс — может отсутствовать на YouTube\n"
        "• Приватный плейлист — не открывается\n"
        "• Геоблок — попробуй VPN\n"
        "• Скажи название → /sub для поддержки\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>❌ Не распознаёт голосовое</b>\n\n"
        "• Слишком короткое — минимум 10 сек\n"
        "• Слишком тихо — ближе к источнику\n"
        "• Ремикс/кавер — Shazam не знает\n"
        "• Не списалось — попробуй ещё раз\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>❌ Не хватает баланса</b>\n\n"
        "• /balance — посмотреть сколько\n"
        "• /buy — как пополнить\n"
        "• /trial — если ещё не использовал\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>🆘 Совсем не работает</b>\n\n"
        "Напиши @admin с описанием проблемы и скриншотом."
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


@router.callback_query(F.data == "user:hint_download")
async def cb_hint_download(call: CallbackQuery) -> None:
    await call.message.answer(
        "🎵 Пришли ссылку на трек:\n\n"
        "<b>Spotify · SoundCloud · YouTube · Яндекс · Bandcamp · VK · Mixcloud</b>\n\n"
        "Или нажми 🎤 для распознавания."
    )
    await call.answer()

# ============================================================
# 📋 ПЛЕЙЛИСТ — инструкция
# ============================================================

@router.message(F.text == "📋 Плейлист")
async def btn_playlist_hint(message: Message) -> None:
    if await is_banned(message.from_user.id):
        return
    text = (
        "📋 <b>Скачать плейлист</b>\n\n"
        "Пришли ссылку на <b>плейлист или альбом</b> —\n"
        "скачаю все треки по порядку.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Что поддерживается:</b>\n\n"
        "<b>Spotify:</b>\n"
        "  <code>open.spotify.com/album/...</code>\n"
        "  <code>open.spotify.com/playlist/...</code>\n\n"
        "<b>SoundCloud:</b>\n"
        "  <code>soundcloud.com/artist/sets/...</code>\n\n"
        "<b>YouTube:</b>\n"
        "  <code>youtube.com/playlist?list=...</code>\n"
        "  <code>youtube.com/watch?v=...&amp;list=...</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <b>Ограничения:</b>\n"
        "• Максимум <b>20 треков</b> за раз\n"
        "• Приватные плейлисты не работают\n"
        "• Если трек не найден — придёт сообщение\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Как это выглядит:</b>\n"
        "  1. Пришлёшь ссылку\n"
        "  2. Я скачиваю по одному (5-20 сек каждый)\n"
        "  3. Прогресс: <i>1/10, 2/10...</i>\n"
        "  4. Пропуски — с пометкой что не нашёл"
    )
    await message.answer(text, reply_markup=cancel_kb())


@router.callback_query(F.data == "user:help_playlist")
async def cb_help_playlist(call: CallbackQuery) -> None:
    text = (
        "📋 <b>Плейлисты — подробно</b>\n\n"
        "<b>Как работает:</b>\n"
        "Бот видит что ссылка на плейлист (а не трек),\n"
        "и скачивает <b>все треки по очереди</b>.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Лимиты:</b>\n"
        "• До <b>20 треков</b> за раз\n"
        "• Каждый — 5-20 сек\n"
        "• Общее время: до 5 минут на 20 треков\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Оплата:</b>\n"
        "• Подписка — <b>безлимит</b>\n"
        "• Баланс — цена <b>за каждый трек</b> отдельно\n"
        "• Кэш — если трек уже качал, <b>бесплатно</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Совет:</b>\n"
        "Скачиваешь много плейлистов? Возьми подписку /sub — выгоднее."
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()


# ============================================================
# 📝 ТЕКСТ ПЕСНИ — Lyrics
# ============================================================

@router.message(F.text == "📝 Текст песни")
async def btn_lyrics(message: Message, state: FSMContext) -> None:
    if await is_banned(message.from_user.id):
        return
    await state.set_state(UserLyricsStates.waiting_query)
    await message.answer(
        "📝 <b>Текст песни</b>\n\n"
        "Напиши в формате:\n"
        "<code>Исполнитель - Название</code>\n\n"
        "Например:\n"
        "  <code>Imagine Dragons - Believer</code>\n"
        "  <code>Баста - Сансара</code>\n"
        "  <code>Coldplay - Yellow</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Или:</b>\n"
        "  • Скачай трек — тогда /lyrics без аргументов сам подхватит\n"
        "  • Можно через запятую: <code>Imagine Dragons, Believer</code>\n\n"
        "/cancel — отмена",
        reply_markup=lyrics_cancel_kb(),
    )


@router.message(Command("lyrics"))
async def cmd_lyrics(message: Message, state: FSMContext) -> None:
    if await is_banned(message.from_user.id):
        return
    # Проверяем аргументы
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        # Есть аргументы — сразу ищем
        query = parts[1].strip()
        await _do_lyrics_search(message, query)
        return

    # Без аргументов — пробуем взять последний трек
    last_track = await db.get_user_downloads(message.from_user.id, limit=1)
    if last_track:
        t = last_track[0]
        artist = t.get("performer") or ""
        title = t.get("title") or ""
        if title:
            await message.answer(
                f"📝 Ищу текст: <b>{html.escape(artist)} — {html.escape(title)}</b>..."
            )
            await _do_lyrics_search(message, f"{artist} - {title}")
            return

    # Ничего нет — просим ввести
    await state.set_state(UserLyricsStates.waiting_query)
    await message.answer(
        "📝 <b>Текст песни</b>\n\n"
        "Напиши: <code>Исполнитель - Название</code>\n\n"
        "Например: <code>Imagine Dragons - Believer</code>\n\n"
        "/cancel — отмена",
        reply_markup=lyrics_cancel_kb(),
    )


@router.message(UserLyricsStates.waiting_query)
async def msg_lyrics_query(message: Message, state: FSMContext) -> None:
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    query = (message.text or "").strip()
    if len(query) < 3:
        await message.answer("⚠️ Слишком коротко. Напиши: Исполнитель - Название")
        return
    await state.clear()
    await _do_lyrics_search(message, query)


@router.callback_query(F.data == "user:lyrics_cancel")
async def cb_lyrics_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await call.message.edit_text("❌ Отменено.")
    except Exception:
        pass
    await call.answer()


async def _do_lyrics_search(message: Message, query: str) -> None:
    """Ищет текст и отправляет."""
    from services.lyrics import fetch_lyrics, clean_lyrics
    import asyncio

    # Парсим "Исполнитель - Название" или "Исполнитель, Название"
    artist = ""
    title = query
    for sep in [" - ", " – ", " — ", ", "]:
        if sep in query:
            parts = query.split(sep, 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            break

    status = await message.answer("🔎 Ищу текст...")
    result = await asyncio.to_thread(
        lambda: __import__("asyncio").run(fetch_lyrics(artist, title))
    ) if False else await fetch_lyrics(artist, title)

    if not result:
        try:
            await status.edit_text(
                f"❌ <b>Текст не найден</b>\n\n"
                f"Исполнитель: <i>{html.escape(artist or '—')}</i>\n"
                f"Название: <i>{html.escape(title)}</i>\n\n"
                "💡 <b>Что попробовать:</b>\n"
                "  • Проверь написание\n"
                "  • Попробуй по-другому: <code>Название - Исполнитель</code>\n"
                "  • Песня может быть не в базе lrclib\n"
                "  • Редкие/новые треки отсутствуют"
            )
        except Exception:
            pass
        return

    lyrics_text = clean_lyrics(result["lyrics"])
    source = result["source"]

    header = (
        f"📝 <b>{html.escape(artist or '—')} — {html.escape(title)}</b>\n"
        f"<i>Источник: {source}</i>\n\n"
    )

    # Telegram лимит 4096, оставим место под header
    MAX = 3800
    escaped_lyrics = html.escape(lyrics_text)

    if len(header) + len(escaped_lyrics) <= 4096:
        try:
            await status.edit_text(header + escaped_lyrics)
        except Exception as e:
            await status.edit_text(f"❌ Ошибка отправки: {e}")
        return

    # Разбиваем на части
    await status.delete()
    await message.answer(header + "<i>(текст будет частями)</i>")

    chunk_size = MAX
    chunks = []
    escaped = escaped_lyrics
    while escaped:
        # Пытаемся разбить по \n\n
        if len(escaped) <= chunk_size:
            chunks.append(escaped)
            break
        cut = escaped.rfind("\n\n", 0, chunk_size)
        if cut < 1000:
            cut = escaped.rfind("\n", 0, chunk_size)
        if cut < 1000:
            cut = chunk_size
        chunks.append(escaped[:cut])
        escaped = escaped[cut:].lstrip("\n")

    for i, chunk in enumerate(chunks, 1):
        part_header = f"<b>Часть {i}/{len(chunks)}</b>\n\n" if len(chunks) > 1 else ""
        try:
            await message.answer(part_header + chunk)
        except Exception as e:
            logger.exception("chunk send failed")
            await message.answer(f"❌ Ошибка части {i}: {e}")
            break


@router.callback_query(F.data == "user:help_lyrics")
async def cb_help_lyrics(call: CallbackQuery) -> None:
    text = (
        "📝 <b>Текст песни</b>\n\n"
        "<b>Как использовать:</b>\n\n"
        "🔹 <b>Кнопка в меню</b>\n"
        "Нажми <b>📝 Текст песни</b> → напиши:\n"
        "<code>Исполнитель - Название</code>\n\n"
        "🔹 <b>Команда /lyrics</b>\n"
        "<code>/lyrics Imagine Dragons - Believer</code>\n"
        "→ сразу найдёт и пришлёт\n\n"
        "🔹 <b>После скачивания</b>\n"
        "<code>/lyrics</code> без аргументов\n"
        "→ возьмёт последний скачанный трек\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Источники:</b>\n"
        "• <b>lrclib.net</b> — большая открытая база\n"
        "• <b>lyrics.ovh</b> — fallback\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Если не находит:</b>\n"
        "• Редкая/новая песня — может отсутствовать\n"
        "• Проверь написание\n"
        "• Попробуй по-английски если русская\n"
        "• Многие ремиксы без официального текста\n\n"
        "💰 <b>Бесплатно</b> — текст не тратит баланс."
    )
    try:
        await call.message.edit_text(text, reply_markup=back_to_help())
    except Exception:
        await call.message.answer(text, reply_markup=back_to_help())
    await call.answer()

@router.callback_query(F.data == "user:cancel")
async def cb_user_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await call.message.edit_text("❌ Отменено.")
    except Exception:
        pass
    await call.answer()