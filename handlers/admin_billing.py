import html
import logging

import config
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import postgres_db as db
from keyboards.admin import withdrawal_kb, withdrawal_help_kb, admin_menu, back_kb, balance_kb, billing_kb, prices_kb
from states import AdminBillingStates
from utils.checks import is_admin

router = Router(name="admin_billing")
logger = logging.getLogger(__name__)


def _e(v):
    return html.escape(str(v)) if v is not None else "—"


async def _guard_cb(call: CallbackQuery) -> bool:
    if not await is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return False
    return True


async def _guard_msg(message: Message) -> bool:
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return False
    return True


# ============================================================
# BILLING MODE
# ============================================================

@router.callback_query(F.data == "adm:billing")
async def cb_billing(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    mode = await db.get_billing_mode()
    text = (
        "⚙️ <b>Режим биллинга</b>\n\n"
        "Управляй моделью монетизации:\n\n"
        f"• 💎 <b>Подписка</b>: {'✅ ВКЛ' if mode['subscription_enabled'] else '❌ ВЫКЛ'}\n"
        f"• 💳 <b>Pay-per-use</b>: {'✅ ВКЛ' if mode['pay_per_use_enabled'] else '❌ ВЫКЛ'}\n"
        f"• 🎁 <b>Бесплатных в день</b>: {mode['free_actions_per_day']}"
    )
    try:
        await call.message.edit_text(text, reply_markup=billing_kb(mode))
    except Exception:
        await call.message.answer(text, reply_markup=billing_kb(mode))
    await call.answer()


@router.callback_query(F.data == "adm:bill_sub")
async def cb_bill_sub(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    mode = await db.get_billing_mode()
    await db.set_billing_mode(subscription_enabled=not mode["subscription_enabled"])
    await call.answer("Изменено")
    await cb_billing(call)


@router.callback_query(F.data == "adm:bill_ppu")
async def cb_bill_ppu(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    mode = await db.get_billing_mode()
    await db.set_billing_mode(pay_per_use_enabled=not mode["pay_per_use_enabled"])
    await call.answer("Изменено")
    await cb_billing(call)


@router.callback_query(F.data == "adm:bill_free")
async def cb_bill_free(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    await state.set_state(AdminBillingStates.bill_free_count)
    await call.message.answer("Сколько бесплатных действий в день? (0 = отключить). /cancel")
    await call.answer()


@router.message(AdminBillingStates.bill_free_count)
async def msg_bill_free(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно число >= 0.")
        return
    await state.clear()
    await db.set_billing_mode(free_actions_per_day=int(raw))
    await message.answer(f"Бесплатных в день: {raw}", reply_markup=admin_menu())


# ============================================================
# ACTION PRICES
# ============================================================

@router.callback_query(F.data == "adm:prices")
async def cb_prices(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    prices = await db.get_action_prices()
    text = "💵 <b>Цены действий</b>\n\nТапни чтобы изменить цену в ⭐"
    try:
        await call.message.edit_text(text, reply_markup=prices_kb(prices, config.ACTION_KEYS))
    except Exception:
        await call.message.answer(text, reply_markup=prices_kb(prices, config.ACTION_KEYS))
    await call.answer()


@router.callback_query(F.data.startswith("adm:price_act:"))
async def cb_price_act(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    action_key = call.data.split(":")[-1]
    title = config.ACTION_KEYS.get(action_key, action_key)
    prices = await db.get_action_prices()
    cur = prices.get(action_key, 0)
    await state.set_state(AdminBillingStates.price_action_edit)
    await state.update_data(action_key=action_key)
    await call.message.answer(
        f"💵 <b>{title}</b>\n\nТекущая цена: <b>{cur}⭐</b>\n\nВведи новую (0 = бесплатно). /cancel"
    )
    await call.answer()


@router.message(AdminBillingStates.price_action_edit)
async def msg_price_act(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно число >= 0.")
        return
    data = await state.get_data()
    await state.clear()
    await db.set_action_price(data["action_key"], int(raw))
    await message.answer(f"Цена обновлена: {raw}⭐", reply_markup=admin_menu())


# ============================================================
# USER BALANCE
# ============================================================

@router.callback_query(F.data.startswith("adm:u_bal:"))
async def cb_user_bal(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    bal = await db.get_balance(uid)
    txs = await db.get_transactions(uid, limit=10)
    text = f"💳 <b>Баланс</b> юзера <code>{uid}</code>\n\n💰 Текущий: <b>{bal}⭐</b>\n\n"
    if txs:
        text += "📜 <b>История:</b>\n"
        for tx in txs:
            sign = "+" if tx["amount"] > 0 else ""
            act = f" · {tx['action']}" if tx["action"] else ""
            text += f"  {sign}{tx['amount']}⭐ · {tx['kind']}{act}\n"
    else:
        text += "📜 Пусто."
    try:
        await call.message.edit_text(text, reply_markup=balance_kb(uid))
    except Exception:
        await call.message.answer(text, reply_markup=balance_kb(uid))
    await call.answer()


@router.callback_query(F.data.startswith("adm:bal_add:"))
async def cb_bal_add(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    parts = call.data.split(":")
    uid = int(parts[2]); amount = int(parts[3])
    new_bal = await db.add_balance(uid, amount, kind="topup",
                                    note=f"admin:{call.from_user.id}",
                                    created_by=call.from_user.id)
    await call.answer(f"+{amount}⭐ → {new_bal}⭐", show_alert=True)
    call.data = f"adm:u_bal:{uid}"
    await cb_user_bal(call)


@router.callback_query(F.data.startswith("adm:bal_zero:"))
async def cb_bal_zero(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    bal = await db.get_balance(uid)
    if bal > 0:
        await db.add_balance(uid, -bal, kind="manual", note="admin reset",
                              created_by=call.from_user.id)
    await call.answer("Баланс обнулён", show_alert=True)
    call.data = f"adm:u_bal:{uid}"
    await cb_user_bal(call)


@router.callback_query(F.data.startswith("adm:bal_custom:"))
async def cb_bal_custom(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    await state.set_state(AdminBillingStates.balance_custom)
    await state.update_data(target_uid=uid)
    await call.message.answer(
        f"Сколько ⭐ начислить юзеру <code>{uid}</code>? (можно отрицательное). /cancel"
    )
    await call.answer()


@router.message(AdminBillingStates.balance_custom)
async def msg_bal_custom(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    try:
        amount = int(raw)
    except ValueError:
        await message.answer("Нужно целое число.")
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    await state.clear()
    new_bal = await db.add_balance(uid, amount, kind="manual",
                                    note=f"admin:{message.from_user.id}",
                                    created_by=message.from_user.id)
    await message.answer(
        f"{'+' if amount >= 0 else ''}{amount}⭐ → <code>{uid}</code>\nБаланс: <b>{new_bal}⭐</b>",
        reply_markup=admin_menu(),
    )

# ============================================================
# WITHDRAWAL (вывод средств)
# ============================================================

@router.callback_query(F.data == "adm:withdrawal")
async def cb_withdrawal(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    stats = await db.get_withdrawal_stats()
    history = await db.get_withdrawals(limit=5)
    text = (
        "📤 <b>Вывод средств</b>\n\n"
        f"💵 Всего заработано: <b>{stats['total_income']}⭐</b>\n"
        f"  ├ подписки: {stats['subs_income']}⭐\n"
        f"  └ пополнения: {stats['topup_income']}⭐\n\n"
        f"👥 На балансах юзеров: <b>{stats['on_balances']}⭐</b>\n"
        f"  <i>(обязательства перед юзерами — нельзя выводить)</i>\n\n"
        f"📤 Уже выведено: <b>{stats['withdrawn']}⭐</b>\n\n"
        f"✅ <b>Доступно к выводу: {stats['available']}⭐</b>\n"
    )
    if history:
        text += "\n📜 <b>Последние выводы:</b>\n"
        for w in history:
            note = f" · {w['note']}" if w['note'] else ""
            text += f"  • {w['amount']}⭐{note} · {w['created_at'].strftime('%d.%m.%Y')}\n"
    try:
        await call.message.edit_text(text, reply_markup=withdrawal_kb(stats, bool(history)))
    except Exception:
        await call.message.answer(text, reply_markup=withdrawal_kb(stats, bool(history)))
    await call.answer()


@router.callback_query(F.data == "adm:wd_help")
async def cb_wd_help(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    text = (
        "📖 <b>Как вывести Stars</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Шаг 1.</b> Открой @BotFather\n\n"
        "<b>Шаг 2.</b> /mybots → выбери своего бота\n\n"
        "<b>Шаг 3.</b> Нажми <b>Payments</b>\n\n"
        "<b>Шаг 4.</b> Нажми <b>Stars</b> → <b>Withdraw</b>\n\n"
        "<b>Шаг 5.</b> Укажи сумму и кошелёк TON (Fragment)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Условия Telegram:</b>\n"
        "• Минимум: <b>1000⭐</b> за один вывод\n"
        "• Комиссия: 0%\n"
        "• Срок: до <b>21 дня</b>\n"
        "• Куда: кошелёк TON\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Как это работает:</b>\n"
        "1. Юзеры платят ⭐ → они в кошельке бота (в Telegram)\n"
        "2. Бот показывает сколько «свободно» (заработано − на балансах − уже выведено)\n"
        "3. Ты выводишь через @BotFather\n"
        "4. Возвращаешься в бот → <b>📝 Записать вывод</b> → вводишь сумму\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Где взять кошелёк TON:</b>\n"
        "• <b>@wallet</b> в Telegram\n"
        "• Fragment.com\n"
        "• Любой TON-кошелёк\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Важно:</b>\n"
        "⚠️ Не выводи «на балансах юзеров» — они ещё могут потратить\n"
        "⚠️ Telegram не даёт вывести &lt; 1000⭐\n"
        "⚠️ Комиссия сети TON оплачивается с кошелька"
    )
    try:
        await call.message.edit_text(text, reply_markup=withdrawal_help_kb())
    except Exception:
        await call.message.answer(text, reply_markup=withdrawal_help_kb())
    await call.answer()


@router.callback_query(F.data == "adm:wd_add")
async def cb_wd_add(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    stats = await db.get_withdrawal_stats()
    if stats['available'] <= 0:
        await call.answer("Нечего выводить — доступно 0⭐", show_alert=True)
        return
    await state.set_state(AdminBillingStates.withdraw_amount)
    await call.message.answer(
        f"📝 <b>Запись о выводе</b>\n\n"
        f"Доступно: <b>{stats['available']}⭐</b>\n"
        f"Минимум для реального вывода: 1000⭐\n\n"
        f"Сколько вывел (в ⭐)?\n/cancel — отмена"
    )
    await call.answer()


@router.message(AdminBillingStates.withdraw_amount)
async def msg_wd_amount(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("Нужно положительное число.")
        return
    amount = int(raw)
    stats = await db.get_withdrawal_stats()
    if amount > stats['available']:
        await message.answer(
            f"⚠️ Слишком много. Доступно: <b>{stats['available']}⭐</b>"
        )
        return
    await state.update_data(withdraw_amount=amount)
    await state.set_state(AdminBillingStates.withdraw_note)
    await message.answer(
        f"📝 Сумма: <b>{amount}⭐</b>\n\nДобавь заметку (номер транзакции, дата, кошелёк) или /skip:"
    )


@router.message(AdminBillingStates.withdraw_note)
async def msg_wd_note(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    note = "" if raw == "/skip" else raw[:200]
    data = await state.get_data()
    amount = data.get("withdraw_amount", 0)
    await state.clear()
    await db.add_withdrawal(amount, note, message.from_user.id)
    await message.answer(
        f"✅ Записано: <b>{amount}⭐</b>"
        + (f"\n📝 {note}" if note else ""),
        reply_markup=admin_menu(),
    )


@router.callback_query(F.data == "adm:wd_history")
async def cb_wd_history(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    history = await db.get_withdrawals(limit=50)
    if not history:
        await call.answer("История пуста", show_alert=True)
        return
    text = "📜 <b>История выводов</b>\n\n"
    total = 0
    for w in history:
        note = f" · {w['note']}" if w['note'] else ""
        text += f"• {w['amount']}⭐{note} · {w['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
        total += w['amount']
    text += f"\n<b>Итого выведено: {total}⭐</b>"
    try:
        await call.message.edit_text(text, reply_markup=withdrawal_kb({}, True))
    except Exception:
        await call.message.answer(text, reply_markup=withdrawal_kb({}, True))
    await call.answer()

@router.callback_query(F.data == "adm:earnings")
async def cb_earnings(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    stats = await db.get_withdrawal_stats()
    text = (
        "💵 <b>Заработок</b>\n\n"
        f"📈 Всего заработано: <b>{stats['total_income']}⭐</b>\n"
        f"  ├ подписки: {stats['subs_income']}⭐\n"
        f"  └ пополнения: {stats['topup_income']}⭐\n\n"
        f"👥 На балансах юзеров: <b>{stats['on_balances']}⭐</b>\n"
        f"📤 Уже выведено: <b>{stats['withdrawn']}⭐</b>\n\n"
        f"✅ <b>Доступно к выводу: {stats['available']}⭐</b>\n\n"
        f"<i>Перейти к выводу:</i> /admin → 📤 Вывод"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_kb())
    except Exception:
        await call.message.answer(text, reply_markup=back_kb())
    await call.answer()