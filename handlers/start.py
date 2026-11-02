import config
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import postgres_db as db
from keyboards.main import main_menu
from locales import t
from utils.checks import is_admin, is_banned

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if await is_banned(message.from_user.id):
        await message.answer(t("banned_alert"))
        return
    await db.upsert_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
    )
    admin = await is_admin(message.from_user.id)
    await message.answer(
        t("start_hello", name=message.from_user.first_name or "друг"),
        reply_markup=main_menu(is_admin=admin),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    admin = await is_admin(message.from_user.id)
    await message.answer(t("menu_title"), reply_markup=main_menu(is_admin=admin))


@router.message(F.text == "🎵 Скачать трек")
async def btn_download(message: Message) -> None:
    await message.answer(t("download_hint"))


@router.message(F.text == "❓ Помощь")
async def btn_help(message: Message) -> None:
    await message.answer(t("help_text"))


@router.message(F.text == "📊 Мой профиль")
async def btn_profile(message: Message) -> None:
    uid = message.from_user.id
    user = await db.get_user(uid)
    if not user:
        await message.answer("⚠️ Сначала /start")
        return
    paid = await db.is_paid(uid)
    sub_end = user["subscription_end"].strftime("%d.%m.%Y") if user["subscription_end"] else "—"
    balance = await db.get_balance(uid)
    status = "💎 Премиум" if paid else "🆓 Бесплатный"
    ok, used, limit = await db.can_download(uid)
    limit_text = "без лимита" if limit < 0 else f"{used}/{limit} сегодня"
    trial = await db.get_trial()
    trial_hint = ""
    if trial.get("enabled") and not user["trial_used"] and not paid:
        trial_hint = f"\n\n🎁 Доступен триал на {trial['days']} дн! Напиши /trial"
    # Фичи юзера
    feats = await db.get_user_features(uid)
    feats_text = ""
    active_feats = [f for f in feats if f["uses_left"] > 0]
    if active_feats:
        feats_text = "\n\n⭐ <b>Активные фичи:</b>\n"
        for f in active_feats:
            feats_text += f"  • {f['name']} — {f['uses_left']} исп.\n"
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"ID: <code>{uid}</code>\n"
        f"Имя: {message.from_user.first_name or '—'}\n"
        f"Статус: <b>{status}</b>\n"
        f"Подписка до: <b>{sub_end}</b>\n"
        f"💳 Баланс: <b>{balance}⭐</b>\n"
        f"Скачиваний: <b>{limit_text}</b>"
        f"{trial_hint}"
        f"{feats_text}"
    )


@router.message(F.text == "👑 Админ-панель")
async def btn_admin(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return
    from keyboards.admin import admin_menu
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu())


@router.message(Command("trial"))
async def cmd_trial(message: Message) -> None:
    uid = message.from_user.id
    trial = await db.get_trial()
    if not trial.get("enabled"):
        await message.answer("🎁 Триал недоступен.")
        return
    if await db.is_paid(uid):
        await message.answer("✅ У тебя уже есть активная подписка.")
        return
    ok = await db.activate_trial(uid)
    if ok:
        await message.answer(f"🎁 Триал активирован на {trial['days']} дн! Приятного пользования.")
    else:
        await message.answer("❌ Триал уже был использован.")

@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    uid = message.from_user.id
    bal = await db.get_balance(uid)
    prices = await db.get_action_prices()
    txs = await db.get_transactions(uid, limit=10)
    text = f"💳 <b>Баланс</b>\n\n💰 У тебя: <b>{bal}⭐</b>\n\n📋 <b>Цены:</b>\n"
    for key, title in config.ACTION_KEYS.items():
        text += f"  • {title}: <b>{prices.get(key, 0)}⭐</b>\n"
    if txs:
        text += "\n📜 <b>Последние:</b>\n"
        for tx in txs:
            sign = "+" if tx["amount"] > 0 else ""
            text += f"  {sign}{tx['amount']}⭐ · {tx['kind']}\n"
    text += "\n\n💳 Пополнить: /buy · 💎 Подписка: /sub"
    await message.answer(text)


@router.message(Command("buy"))
async def cmd_buy(message: Message) -> None:
    uid = message.from_user.id
    bal = await db.get_balance(uid)
    prices = await db.get_action_prices()
    text = (
        "💳 <b>Пополнение баланса</b>\n\n"
        f"💰 Текущий баланс: <b>{bal}⭐</b>\n\n"
        "📋 <b>Цены за действия:</b>\n"
    )
    for key, title in config.ACTION_KEYS.items():
        text += f"  • {title}: <b>{prices.get(key, 0)}⭐</b>\n"
    text += (
        "\n━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Как пополнить:</b>\n\n"
        "🔹 <b>Через админа (сейчас):</b>\n"
        "  Напиши @admin — он зачислит на баланс\n\n"
        "🔹 <b>Через Telegram Stars (скоро):</b>\n"
        "  Прямая оплата в боте, картой или звёздами\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Зачем нужен баланс:</b>\n"
        "  • Скачивание треков — списывается цена\n"
        "  • Распознавание музыки — списывается цена\n"
        "  • Кэш — повторные скачивания <b>бесплатно</b>\n\n"
        "💡 <b>Выгоднее подписка:</b> /sub — безлимит на всё"
    )
    await message.answer(text)