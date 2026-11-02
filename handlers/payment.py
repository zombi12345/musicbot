"""Telegram Stars (XTR) payments: баланс + подписка."""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from database import postgres_db as db

router = Router(name="payment")
logger = logging.getLogger(__name__)

BALANCE_PACKS = [50, 100, 250, 500]


# ============================================================
# ПОПОЛНЕНИЕ БАЛАНСА
# ============================================================

@router.callback_query(F.data.startswith("pay:balance:"))
async def cb_buy_balance(call: CallbackQuery) -> None:
    try:
        amount = int(call.data.split(":")[-1])
    except (ValueError, IndexError):
        await call.answer("Неверная сумма", show_alert=True)
        return
    if amount not in BALANCE_PACKS:
        await call.answer("Недоступный пакет", show_alert=True)
        return

    await call.message.answer_invoice(
        title=f"Пополнение баланса на {amount}⭐",
        description=(
            f"{amount} звёзд будут зачислены на баланс.\n"
            f"1⭐ = 1 звёздочка.\n"
            f"Баланс используется для скачивания треков."
        ),
        payload=f"balance:{call.from_user.id}:{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"Баланс {amount}⭐", amount=amount)],
    )
    await call.answer()


# ============================================================
# ПОКУПКА ПОДПИСКИ
# ============================================================

@router.callback_query(F.data.startswith("pay:sub:"))
async def cb_buy_sub(call: CallbackQuery) -> None:
    plan_key = call.data.split(":")[-1]
    pricing = await db.get_pricing()
    info = pricing.get(plan_key)
    if not info:
        await call.answer("Тариф недоступен", show_alert=True)
        return
    days = int(info["days"])
    stars = int(info["stars"])

    await call.message.answer_invoice(
        title=f"Подписка Premium — {days} дней",
        description=(
            f"Безлимит на скачивание, распознавание и плейлисты на {days} дней.\n"
            f"После оплаты подписка активируется автоматически."
        ),
        payload=f"sub:{call.from_user.id}:{days}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"Подписка {days} дней", amount=stars)],
    )
    await call.answer()


# ============================================================
# PRE-CHECKOUT (≤10 секунд, локальная валидация)
# ============================================================

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    payload = query.invoice_payload or ""
    parts = payload.split(":")
    ok = False
    if len(parts) == 3 and parts[0] in ("balance", "sub"):
        try:
            uid = int(parts[1])
            val = int(parts[2])
            ok = uid == query.from_user.id and val > 0
        except ValueError:
            ok = False
    await query.answer(
        ok=ok,
        error_message=None if ok else "Счёт устарел. Создайте новый.",
    )


# ============================================================
# SUCCESSFUL_PAYMENT (идемпотентно)
# ============================================================

@router.message(F.successful_payment)
async def on_paid(message: Message) -> None:
    sp = message.successful_payment
    payload = sp.invoice_payload or ""
    charge_id = sp.telegram_payment_charge_id
    amount = sp.total_amount
    uid = message.from_user.id

    # 1) СНАЧАЛА фиксируем платёж (идемпотентность)
    is_new = await db.record_payment(
        charge_id=charge_id,
        user_id=uid,
        amount=amount,
        days=0,
        source="stars",
    )
    if not is_new:
        logger.info("Duplicate payment ignored: %s", charge_id)
        return

    # 2) Выдаём товар
    parts = payload.split(":")
    try:
        if len(parts) >= 2 and parts[0] == "balance":
            new_bal = await db.add_balance(
                uid, amount, kind="topup", note=f"stars:{charge_id}"
            )
            await message.answer(
                f"✅ <b>Баланс пополнен!</b>\n\n"
                f"💰 +{amount}⭐ → <b>{new_bal}⭐</b>\n\n"
                f"<i>Чек: <code>{charge_id}</code></i>"
            )
        elif len(parts) >= 3 and parts[0] == "sub":
            try:
                days = int(parts[2])
            except (ValueError, IndexError):
                days = 30
            await db.set_subscription(
                uid, days, stars_paid=amount, source="stars"
            )
            await message.answer(
                f"🎉 <b>Подписка активирована!</b>\n\n"
                f"💎 {days} дней безлимита\n"
                f"⭐ Оплачено: {amount}\n\n"
                f"<i>Чек: <code>{charge_id}</code></i>"
            )
        else:
            await message.answer(
                f"✅ Платёж получен ({amount}⭐).\n"
                f"<i>Чек: <code>{charge_id}</code></i>"
            )
    except Exception as e:
        logger.exception("payment delivery failed")
        await message.answer(
            f"⚠️ Платёж получен, но выдача не удалась.\n"
            f"Напишите @admin с чеком: <code>{charge_id}</code>"
        )


# ============================================================
# /paysupport — обязательная команда по правилам Telegram
# ============================================================

@router.message(Command("paysupport"))
async def paysupport(message: Message) -> None:
    await message.answer(
        "💬 <b>Поддержка по платежам</b>\n\n"
        "Если у вас проблема с оплатой или нужен возврат — напишите @admin.\n\n"
        "Укажите:\n"
        "  • Telegram ID\n"
        "  • Дату и сумму платежа\n"
        "  • Что не работает\n\n"
        "💡 Все чеки сохраняются — по ним можно оформить возврат."
    )