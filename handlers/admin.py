import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from database import postgres_db as db
from keyboards.admin import (
    admin_menu, admins_kb, back_kb, broadcast_confirm_kb, cache_kb,
    feature_card_kb, features_list_kb, pricing_kb, sub_days_kb,
    trial_kb, user_card_kb, user_features_pick_kb, users_list_kb,
)
from states import AdminStates
from utils.broadcast import broadcast
from utils.checks import is_admin, is_main_admin

router = Router(name="admin")
logger = logging.getLogger(__name__)

USERS_PER_PAGE = 10


def _e(v) -> str:
    return html.escape(str(v)) if v is not None else "—"


async def _guard_msg(message: Message) -> bool:
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return False
    return True


async def _guard_cb(call: CallbackQuery) -> bool:
    if not await is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return False
    return True


# ============================================================
# ENTRY
# ============================================================

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:back")
async def cb_back(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    await state.clear()
    try:
        await call.message.edit_text("🛠 <b>Админ-панель</b>", reply_markup=admin_menu())
    except Exception:
        await call.message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu())
    await call.answer()


@router.callback_query(F.data == "adm:noop")
async def cb_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=admin_menu())


# ============================================================
# STATS
# ============================================================

@router.callback_query(F.data == "adm:stats")
async def cb_stats(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    s = await db.get_stats()
    trial = await db.get_trial()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего: <b>{s['total']}</b>\n"
        f"💎 Платных: <b>{s['paid']}</b>\n"
        f"🆓 Бесплатных: <b>{s['free']}</b>\n"
        f"🚫 Забанено: <b>{s['banned']}</b>\n"
        f"🟢 Активных (7д): <b>{s['active7']}</b>\n\n"
        f"⭐ Платежей: <b>{s['total_payments']}</b> · <b>{s['total_stars']}⭐</b>\n"
        f"🎵 Сегодня скачиваний: <b>{s['downloads_today']}</b>\n\n"
        f"🗄 В кэше треков: <b>{s['cached']}</b>\n"
        f"🔁 Хитов: <b>{s['cache_hits']}</b>\n\n"
        f"🎁 Триал: {'✅ ON' if trial['enabled'] else '❌ OFF'} · {trial['days']} дн"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_kb())
    except Exception:
        await call.message.answer(text, reply_markup=back_kb())
    await call.answer()


# ============================================================
# USERS
# ============================================================

@router.callback_query(F.data.startswith("adm:users:"))
async def cb_users(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    try:
        page = int(call.data.split(":")[-1])
    except Exception:
        page = 0
    rows, total = await db.list_users(page, USERS_PER_PAGE)
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    text = f"👥 <b>Юзеры</b> · {total}\nСтр. {page+1}/{total_pages}"
    kb = users_list_kb(rows, page, total_pages) if rows else back_kb()
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:search")
async def cb_search(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    await state.set_state(AdminStates.user_search)
    try:
        await call.message.edit_text(
            "🔍 Введи ID, username или имя для поиска.\n/cancel — отмена",
            reply_markup=back_kb(),
        )
    except Exception:
        await call.message.answer("🔍 Введи запрос. /cancel — отмена")
    await call.answer()


@router.message(AdminStates.user_search)
async def msg_search(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    q = (message.text or "").strip()
    await state.clear()
    if not q:
        await message.answer("⚠️ Пустой запрос.", reply_markup=admin_menu())
        return
    rows, total = await db.list_users(0, USERS_PER_PAGE, search=q)
    if not rows:
        await message.answer(f"🔍 Ничего не найдено: <i>{_e(q)}</i>", reply_markup=back_kb())
        return
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    text = f"🔍 Найдено: {total}\nСтр. 1/{total_pages}"
    await message.answer(text, reply_markup=users_list_kb(rows, 0, total_pages))


@router.callback_query(F.data.startswith("adm:u:"))
async def cb_user_card(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    try:
        uid = int(call.data.split(":")[-1])
    except Exception:
        await call.answer("Bad ID", show_alert=True)
        return
    user = await db.get_user(uid)
    if not user:
        await call.answer("Не найден", show_alert=True)
        return
    feats = await db.get_user_features(uid)
    feats_text = ""
    if feats:
        feats_text = "\n\n⭐ <b>Фичи:</b>\n"
        for f in feats:
            exp = f["expires_at"].strftime("%d.%m.%Y") if f.get("expires_at") else "∞"
            feats_text += f"  • {_e(f['name'])} — {f['uses_left']} исп. до {exp}\n"

    status = "🚫 Бан" if user["is_banned"] else ("💎 Платный" if user["is_paid"] else "🆓 Бесплатный")
    sub_end = user["subscription_end"].strftime("%d.%m.%Y") if user["subscription_end"] else "—"
    trial = "✅ использован" if user["trial_used"] else "🎁 не использован"
    text = (
        f"👤 <b>{_e(user['first_name'])}</b>\n"
        f"ID: <code>{uid}</code>\n"
        f"@{_e(user['username'])}\n"
        f"Статус: {status}\n"
        f"Подписка до: <b>{sub_end}</b>\n"
        f"Триал: {trial}\n"
        f"Регистрация: {user['created_at'].strftime('%d.%m.%Y')}"
        f"{feats_text}"
    )
    kb = user_card_kb(uid, user["is_banned"], user["is_paid"])
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:u_ban:"))
async def cb_user_ban(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    await db.set_ban(uid, True)
    await call.answer("🚫 Забанен")
    call.data = f"adm:u:{uid}"
    await cb_user_card(call)


@router.callback_query(F.data.startswith("adm:u_unban:"))
async def cb_user_unban(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    await db.set_ban(uid, False)
    await call.answer("✅ Разбанен")
    call.data = f"adm:u:{uid}"
    await cb_user_card(call)


@router.callback_query(F.data.startswith("adm:u_sub_add:"))
async def cb_user_sub_add(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    try:
        await call.message.edit_text(
            f"💎 <b>Выдать подписку</b> → <code>{uid}</code>\n\nВыбери срок:",
            reply_markup=sub_days_kb(uid),
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("adm:u_sub_do:"))
async def cb_user_sub_do(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    parts = call.data.split(":")
    uid = int(parts[2]); days = int(parts[3])
    await db.set_subscription(uid, days, 0, "manual", call.from_user.id)
    await call.answer(f"✅ +{days} дней")
    call.data = f"adm:u:{uid}"
    await cb_user_card(call)


@router.callback_query(F.data.startswith("adm:u_sub_custom:"))
async def cb_user_sub_custom(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    await state.set_state(AdminStates.user_sub_custom)
    await state.update_data(target_uid=uid)
    await call.message.answer("✏️ Введи срок в днях (1–3650). /cancel — отмена")
    await call.answer()


@router.message(AdminStates.user_sub_custom)
async def msg_user_sub_custom(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 3650):
        await message.answer("⚠️ Нужно число 1–3650.")
        return
    await state.clear()
    await db.set_subscription(uid, int(raw), 0, "manual", message.from_user.id)
    await message.answer(f"✅ Подписка на {raw} дней выдана юзеру {uid}.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("adm:u_sub_rm:"))
async def cb_user_sub_rm(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    await db.revoke_subscription(uid)
    await call.answer("❌ Подписка снята")
    call.data = f"adm:u:{uid}"
    await cb_user_card(call)


@router.callback_query(F.data.startswith("adm:u_trial_rm:"))
async def cb_user_trial_rm(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    await db.reset_trial_for_user(uid)
    await call.answer("🎁 Триал сброшен")
    call.data = f"adm:u:{uid}"
    await cb_user_card(call)


@router.callback_query(F.data.startswith("adm:u_msg:"))
async def cb_user_msg(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    await state.set_state(AdminStates.user_msg)
    await state.update_data(target_uid=uid)
    await call.message.answer(f"📨 Напиши текст для <code>{uid}</code> (HTML). /cancel")
    await call.answer()


@router.message(AdminStates.user_msg)
async def msg_user_msg(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    await state.clear()
    if not uid:
        await message.answer("⚠️ Потеряли ID.")
        return
    try:
        await message.bot.send_message(uid, message.html_text)
        await message.answer(f"✅ Отправлено <code>{uid}</code>", reply_markup=admin_menu())
    except Exception as e:
        await message.answer(f"❌ {_e(e)[:300]}", reply_markup=admin_menu())


# ============================================================
# USER FEATURES (grant)
# ============================================================

@router.callback_query(F.data.startswith("adm:u_feature:"))
async def cb_user_feature(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    uid = int(call.data.split(":")[-1])
    features = await db.list_one_time_features(only_enabled=True)
    if not features:
        await call.answer("Нет доступных фич", show_alert=True)
        return
    try:
        await call.message.edit_text(
            f"⭐ <b>Выдать фичу</b> → <code>{uid}</code>\n\nВыбери:",
            reply_markup=user_features_pick_kb(features, uid),
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("adm:u_feat_grant:"))
async def cb_user_feat_grant(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    parts = call.data.split(":")
    uid = int(parts[2]); fid = int(parts[3])
    feat = await db.get_one_time_feature(fid)
    if not feat:
        await call.answer("Фича не найдена", show_alert=True)
        return
    await state.set_state(AdminStates.feature_grant_uses)
    await state.update_data(target_uid=uid, feature_id=fid, uses_limit=feat["uses_limit"])
    await call.message.answer(
        f"⭐ <b>{_e(feat['name'])}</b> → <code>{uid}</code>\n\n"
        f"Сколько использований выдать? (по умолчанию {feat['uses_limit']})\n"
        f"/cancel — отмена"
    )
    await call.answer()


@router.message(AdminStates.feature_grant_uses)
async def msg_feat_grant(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    fid = data.get("feature_id")
    default_uses = data.get("uses_limit", 1)
    raw = (message.text or "").strip()
    uses = default_uses if raw == "" else int(raw) if raw.isdigit() else None
    if uses is None or uses < 1:
        await message.answer("⚠️ Нужно число ≥ 1.")
        return
    await state.clear()
    await db.grant_user_feature(uid, fid, uses, message.from_user.id)
    await message.answer(
        f"✅ Выдано {uses} использований фичи <code>{fid}</code> юзеру <code>{uid}</code>.",
        reply_markup=admin_menu(),
    )


# ============================================================
# SUBS overview
# ============================================================

@router.callback_query(F.data == "adm:subs")
async def cb_subs(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        active = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_paid=TRUE") or 0
        expiring = await conn.fetch("""
            SELECT user_id, first_name, subscription_end FROM users
            WHERE is_paid=TRUE AND subscription_end IS NOT NULL
              AND subscription_end BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
            ORDER BY subscription_end LIMIT 10
        """)
    text = f"💎 <b>Подписки</b>\n\nАктивных: <b>{active}</b>\n\n"
    if expiring:
        text += "⚠️ <b>Истекают в течение 7 дней:</b>\n"
        for r in expiring:
            text += f"  • <code>{r['user_id']}</code> {_e(r['first_name'])} — до {r['subscription_end'].strftime('%d.%m.%Y')}\n"
    else:
        text += "✅ Нет истекающих"
    try:
        await call.message.edit_text(text, reply_markup=back_kb())
    except Exception:
        await call.message.answer(text, reply_markup=back_kb())
    await call.answer()


# ============================================================
# TRIAL
# ============================================================

@router.callback_query(F.data == "adm:trial")
async def cb_trial(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    trial = await db.get_trial()
    used = await db.count_trial_used()
    text = (
        "🎁 <b>Триал</b>\n\n"
        f"Статус: {'✅ ВКЛ' if trial['enabled'] else '❌ ВЫКЛ'}\n"
        f"Срок: <b>{trial['days']}</b> дн.\n"
        f"Использовали: <b>{used}</b> чел."
    )
    try:
        await call.message.edit_text(text, reply_markup=trial_kb(trial))
    except Exception:
        await call.message.answer(text, reply_markup=trial_kb(trial))
    await call.answer()


@router.callback_query(F.data == "adm:trial_toggle")
async def cb_trial_toggle(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    trial = await db.get_trial()
    await db.set_trial(not trial["enabled"], trial["days"])
    await call.answer("✅ Изменено")
    await cb_trial(call)


@router.callback_query(F.data == "adm:trial_days")
async def cb_trial_days(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    await state.set_state(AdminStates.trial_days)
    await call.message.answer("✏️ Введи новый срок триала в днях (1–365). /cancel")
    await call.answer()


@router.message(AdminStates.trial_days)
async def msg_trial_days(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 365):
        await message.answer("⚠️ Нужно число 1–365.")
        return
    await state.clear()
    trial = await db.get_trial()
    await db.set_trial(trial["enabled"], int(raw))
    await message.answer(f"✅ Срок триала: {raw} дн.", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:trial_reset_all")
async def cb_trial_reset_all(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    await db.reset_all_trials()
    await call.answer("✅ Флаги сброшены у всех", show_alert=True)
    await cb_trial(call)


# ============================================================
# PRICING
# ============================================================

@router.callback_query(F.data == "adm:pricing")
async def cb_pricing(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    pricing = await db.get_pricing()
    text = "💰 <b>Тарифы</b>\n\nНажми на тариф чтобы изменить дни и звёзды."
    try:
        await call.message.edit_text(text, reply_markup=pricing_kb(pricing))
    except Exception:
        await call.message.answer(text, reply_markup=pricing_kb(pricing))
    await call.answer()


@router.callback_query(F.data.startswith("adm:price_edit:"))
async def cb_price_edit(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    plan = call.data.split(":")[-1]
    await state.set_state(AdminStates.price_days)
    await state.update_data(plan=plan)
    await call.message.answer(f"✏️ Тариф {plan}: введи новые дни (1–3650). /cancel")
    await call.answer()


@router.message(AdminStates.price_days)
async def msg_price_days(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 3650):
        await message.answer("⚠️ Нужно число 1–3650.")
        return
    await state.update_data(days=int(raw))
    await state.set_state(AdminStates.price_stars)
    await message.answer(f"✅ Дни: {raw}\n\nТеперь цена в звёздах (1–100000):")


@router.message(AdminStates.price_stars)
async def msg_price_stars(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 100000):
        await message.answer("⚠️ Нужно число 1–100000.")
        return
    data = await state.get_data()
    await state.clear()
    pricing = await db.get_pricing()
    pricing[data["plan"]] = {"days": data["days"], "stars": int(raw)}
    await db.set_pricing(pricing)
    await message.answer(
        f"✅ Тариф обновлён: {data['days']}д — {raw}⭐",
        reply_markup=admin_menu(),
    )


# ============================================================
# ONE-TIME FEATURES
# ============================================================

@router.callback_query(F.data == "adm:features")
async def cb_features(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    features = await db.list_one_time_features()
    text = "⭐ <b>Разовые функции</b>\n\n"
    if not features:
        text += "Пока нет. Создай первую."
    else:
        text += f"Всего: {len(features)}"
    try:
        await call.message.edit_text(text, reply_markup=features_list_kb(features))
    except Exception:
        await call.message.answer(text, reply_markup=features_list_kb(features))
    await call.answer()


@router.callback_query(F.data.startswith("adm:feat:"))
async def cb_feat_card(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    fid = int(call.data.split(":")[-1])
    f = await db.get_one_time_feature(fid)
    if not f:
        await call.answer("Не найдено", show_alert=True)
        return
    text = (
        f"⭐ <b>{_e(f['name'])}</b>\n"
        f"Code: <code>{_e(f['code'])}</code>\n"
        f"Цена: <b>{f['price_stars']}⭐</b>\n"
        f"Лимит: <b>{f['uses_limit']}</b> исп.\n"
        f"Описание: {_e(f['description'])}\n"
        f"Статус: {'✅' if f['enabled'] else '❌'}"
    )
    try:
        await call.message.edit_text(text, reply_markup=feature_card_kb(fid, f["enabled"]))
    except Exception:
        await call.message.answer(text, reply_markup=feature_card_kb(fid, f["enabled"]))
    await call.answer()


@router.callback_query(F.data.startswith("adm:feat_toggle:"))
async def cb_feat_toggle(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    fid = int(call.data.split(":")[-1])
    f = await db.get_one_time_feature(fid)
    if f:
        await db.update_one_time_feature(fid, enabled=not f["enabled"])
    await call.answer("✅")
    call.data = f"adm:feat:{fid}"
    await cb_feat_card(call)


@router.callback_query(F.data.startswith("adm:feat_rm:"))
async def cb_feat_rm(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    fid = int(call.data.split(":")[-1])
    await db.delete_one_time_feature(fid)
    await call.answer("🗑 Удалено")
    await cb_features(call)


@router.callback_query(F.data == "adm:feat_add")
async def cb_feat_add(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    await state.set_state(AdminStates.feature_add_name)
    await call.message.answer(
        "⭐ <b>Новая фича</b>\n\nШаг 1/4: Название (например, «Скачать плейлист»). /cancel"
    )
    await call.answer()


@router.message(AdminStates.feature_add_name)
async def msg_feat_name(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 100:
        await message.answer("⚠️ 2–100 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(AdminStates.feature_add_desc)
    await message.answer("Шаг 2/4: Описание (или /skip)")


@router.message(AdminStates.feature_add_desc)
async def msg_feat_desc(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    desc = "" if raw == "/skip" else raw[:500]
    await state.update_data(desc=desc)
    await state.set_state(AdminStates.feature_add_price)
    await message.answer("Шаг 3/4: Цена в звёздах (0 — бесплатно):")


@router.message(AdminStates.feature_add_price)
async def msg_feat_price(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 0:
        await message.answer("⚠️ Нужно число ≥ 0.")
        return
    await state.update_data(price=int(raw))
    await state.set_state(AdminStates.feature_add_uses)
    await message.answer("Шаг 4/4: Лимит использований (1–999):")


@router.message(AdminStates.feature_add_uses)
async def msg_feat_uses(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 999):
        await message.answer("⚠️ Нужно число 1–999.")
        return
    data = await state.get_data()
    await state.clear()
    code = f"f_{int(__import__('time').time())}"
    try:
        fid = await db.add_one_time_feature(
            code, data["name"], data.get("desc", ""), data["price"], int(raw)
        )
        await message.answer(
            f"✅ Фича создана #{fid}: {_e(data['name'])}",
            reply_markup=admin_menu(),
        )
    except Exception as e:
        await message.answer(f"❌ {_e(e)[:300]}", reply_markup=admin_menu())


# ============================================================
# ADMINS
# ============================================================

@router.callback_query(F.data == "adm:admins")
async def cb_admins(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    if not await is_main_admin(call.from_user.id):
        await call.answer("Только главный админ", show_alert=True)
        return
    extra = await db.get_extra_admins()
    text = "👑 <b>Админы</b>\n\nenv — из .env (удалить нельзя)\nDB — добавлены через бота"
    try:
        await call.message.edit_text(text, reply_markup=admins_kb(config.ADMIN_IDS, extra))
    except Exception:
        await call.message.answer(text, reply_markup=admins_kb(config.ADMIN_IDS, extra))
    await call.answer()


@router.callback_query(F.data == "adm:admin_add")
async def cb_admin_add(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    if not await is_main_admin(call.from_user.id):
        await call.answer("Только главный админ", show_alert=True)
        return
    await state.set_state(AdminStates.admin_add_id)
    await call.message.answer("🆔 ID нового админа. /cancel")
    await call.answer()


@router.message(AdminStates.admin_add_id)
async def msg_admin_add(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    if not await is_main_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("⚠️ Нужно число.")
        return
    uid = int(raw)
    ok = await db.add_extra_admin(uid, message.from_user.id)
    await state.clear()
    if ok:
        await message.answer(f"✅ <code>{uid}</code> теперь админ.", reply_markup=admin_menu())
        try:
            await message.bot.send_message(uid, "👑 Тебе выданы права администратора.")
        except Exception:
            pass
    else:
        await message.answer("⚠️ Уже админ или env.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("adm:admin_rm:"))
async def cb_admin_rm(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    if not await is_main_admin(call.from_user.id):
        await call.answer("Только главный админ", show_alert=True)
        return
    uid = int(call.data.split(":")[-1])
    await db.remove_extra_admin(uid)
    await call.answer("✅ Удалён")
    await cb_admins(call)


# ============================================================
# BROADCAST
# ============================================================

@router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    await state.set_state(AdminStates.broadcast_text)
    try:
        await call.message.edit_text(
            "📢 <b>Рассылка</b>\n\nПришли текст (HTML разрешён). /cancel — отмена.",
            reply_markup=back_kb(),
        )
    except Exception:
        await call.message.answer("📢 Пришли текст. /cancel — отмена.")
    await call.answer()


@router.message(AdminStates.broadcast_text)
async def msg_broadcast_text(message: Message, state: FSMContext) -> None:
    if not await _guard_msg(message):
        return
    text = message.html_text if message.text else ""
    if not text or len(text) > 4000:
        await message.answer("⚠️ Пустой или слишком длинный (макс 4000).")
        return
    await state.update_data(broadcast_text=text)
    await state.set_state(AdminStates.broadcast_confirm)
    preview = f"📢 <b>Предпросмотр</b>\n\n────────\n{text}\n────────\n\nОтправить всем?"
    await message.answer(preview, reply_markup=broadcast_confirm_kb())


@router.callback_query(F.data == "adm:bcast_cancel", AdminStates.broadcast_confirm)
async def cb_bcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await call.message.edit_text("❌ Отменено.", reply_markup=back_kb())
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == "adm:bcast_send", AdminStates.broadcast_confirm)
async def cb_bcast_send(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(call):
        return
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users WHERE is_banned=FALSE")
    ids = [r["user_id"] for r in rows]
    if not ids:
        await call.message.edit_text("⚠️ Нет юзеров.", reply_markup=back_kb())
        await call.answer()
        return
    msg = await call.message.edit_text(f"📢 0/{len(ids)}")
    await call.answer()
    async def on_progress(done, total, stats):
        try:
            await msg.edit_text(
                f"📢 <b>Рассылка</b>\n{done}/{total}\n"
                f"✅ {stats['sent']} · 🚫 {stats['blocked']} · ❌ {stats['failed']}"
            )
        except Exception:
            pass
    stats = await broadcast(call.bot, ids, text, on_progress=on_progress)
    try:
        await msg.edit_text(
            f"✅ <b>Готово</b>\n\nОтправлено: <b>{stats['sent']}</b>\n"
            f"Заблокировали: {stats['blocked']}\nОшибок: {stats['failed']}",
            reply_markup=back_kb(),
        )
    except Exception:
        pass


# ============================================================
# CACHE
# ============================================================

@router.callback_query(F.data == "adm:cache")
async def cb_cache(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    s = await db.get_stats()
    text = (
        "🗑 <b>Кэш треков</b>\n\n"
        f"Записей: <b>{s['cached']}</b>\n"
        f"Хитов: <b>{s['cache_hits']}</b>"
    )
    try:
        await call.message.edit_text(text, reply_markup=cache_kb())
    except Exception:
        await call.message.answer(text, reply_markup=cache_kb())
    await call.answer()


@router.callback_query(F.data.in_(["adm:cache_temp", "adm:cache_old", "adm:cache_all"]))
async def cb_cache_clear(call: CallbackQuery) -> None:
    if not await _guard_cb(call):
        return
    mode = call.data.split(":")[-1]  # temp | old | all
    deleted = await db.clean_track_cache(mode)
    await call.answer(f"✅ Удалено: {deleted}", show_alert=True)
    await cb_cache(call)