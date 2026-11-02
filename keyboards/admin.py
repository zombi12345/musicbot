from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _b(text, cb):
    return InlineKeyboardButton(text=text, callback_data=cb)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("📊 Статистика", "adm:stats"), _b("📈 Аналитика", "adm:analytics")],
        [_b("👥 Юзеры", "adm:users:0"), _b("💎 Подписки", "adm:subs")],
        [_b("🎁 Триал", "adm:trial"), _b("💰 Прайс", "adm:pricing")],
        [_b("⚙️ Биллинг", "adm:billing"), _b("💵 Цены", "adm:prices")],
        [_b("💵 Заработок", "adm:earnings"), _b("📤 Вывод", "adm:withdrawal")],
        [_b("📢 Рассылка", "adm:broadcast"), _b("📨 По фильтру", "adm:bcast_filter")],
        [_b("💾 Экспорт", "adm:export"), _b("👑 Админы", "adm:admins")],
        [_b("🗑 Кэш", "adm:cache"), _b("📖 Помощь", "adm:help")],
        [_b("🏠 Главное меню", "user:menu")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("⬅️ Назад", "adm:back")],
        [_b("🏠 Главное меню", "user:menu")],
    ])
def users_list_kb(rows, page, total_pages) -> InlineKeyboardMarkup:
    kb = []
    for u in rows:
        icon = "🚫" if u["is_banned"] else ("💎" if u["is_paid"] else "🆓")
        name = (u["first_name"] or "—")[:18]
        kb.append([_b(f"{icon} {name} · {u['user_id']}", f"adm:u:{u['user_id']}")])
    nav = []
    if page > 0:
        nav.append(_b("⬅️", f"adm:users:{page-1}"))
    nav.append(_b(f"{page+1}/{max(total_pages,1)}", "adm:noop"))
    if page < total_pages - 1:
        nav.append(_b("➡️", f"adm:users:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([_b("🔍 Поиск", "adm:search")])
    kb.append([_b("⬅️ Назад", "adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def user_card_kb(uid, is_banned, is_paid) -> InlineKeyboardMarkup:
    kb = []
    # Бан
    if is_banned:
        kb.append([_b("✅ Разбанить", f"adm:u_unban:{uid}")])
    else:
        kb.append([_b("🚫 Забанить", f"adm:u_ban:{uid}")])
    # Подписка
    if is_paid:
        kb.append([_b("❌ Снять подписку", f"adm:u_sub_rm:{uid}")])
        kb.append([_b("✏️ Продлить", f"adm:u_sub_add:{uid}")])
    else:
        kb.append([_b("💎 Дать подписку", f"adm:u_sub_add:{uid}")])
    # Триал
    kb.append([_b("🎁 Сбросить триал", f"adm:u_trial_rm:{uid}")])
    # Фичи
    kb.append([_b("💳 Баланс", f"adm:u_bal:{uid}")])
    # Связь
    kb.append([_b("📨 Написать", f"adm:u_msg:{uid}")])
    kb.append([_b("⬅️ К списку", "adm:users:0")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def sub_days_kb(uid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("7 дней", f"adm:u_sub_do:{uid}:7"), _b("30 дней", f"adm:u_sub_do:{uid}:30")],
        [_b("90 дней", f"adm:u_sub_do:{uid}:90"), _b("365 дней", f"adm:u_sub_do:{uid}:365")],
        [_b("✏️ Свой срок", f"adm:u_sub_custom:{uid}")],
        [_b("⬅️ Назад", f"adm:u:{uid}")],
    ])


def trial_kb(trial) -> InlineKeyboardMarkup:
    on = trial.get("enabled")
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("❌ Выключить" if on else "✅ Включить", "adm:trial_toggle")],
        [_b(f"✏️ Срок ({trial.get('days',0)} дн)", "adm:trial_days")],
        [_b("🔄 Сбросить флаги у всех", "adm:trial_reset_all")],
        [_b("⬅️ Назад", "adm:back")],
    ])


def pricing_kb(pricing) -> InlineKeyboardMarkup:
    kb = []
    for key, val in pricing.items():
        kb.append([_b(f"✏️ {val['days']}д — {val['stars']}⭐", f"adm:price_edit:{key}")])
    kb.append([_b("⬅️ Назад", "adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admins_kb(main_ids, extra_ids) -> InlineKeyboardMarkup:
    kb = []
    for uid in main_ids:
        kb.append([_b(f"{uid} (env)", "adm:noop")])
    for uid in extra_ids:
        kb.append([_b(f"{uid} — ❌ удалить", f"adm:admin_rm:{uid}")])
    kb.append([_b("➕ Добавить ID", "adm:admin_add")])
    kb.append([_b("⬅️ Назад", "adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def features_list_kb(features) -> InlineKeyboardMarkup:
    kb = []
    for f in features:
        icon = "✅" if f["enabled"] else "❌"
        kb.append([_b(f"{icon} {f['name']} · {f['price_stars']}⭐", f"adm:feat:{f['id']}")])
    kb.append([_b("➕ Добавить", "adm:feat_add")])
    kb.append([_b("⬅️ Назад", "adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def feature_card_kb(fid, enabled) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("❌ Отключить" if enabled else "✅ Включить", f"adm:feat_toggle:{fid}")],
        [_b("🗑 Удалить", f"adm:feat_rm:{fid}")],
        [_b("⬅️ К списку", "adm:features")],
    ])


def cache_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("🧹 Очистить temp", "adm:cache_temp")],
        [_b("🗑 Очистить old (>90д)", "adm:cache_old")],
        [_b("⚠️ Очистить ВСЁ", "adm:cache_all")],
        [_b("⬅️ Назад", "adm:back")],
    ])


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("✅ Отправить всем", "adm:bcast_send")],
        [_b("❌ Отмена", "adm:bcast_cancel")],
    ])


def user_features_pick_kb(features, uid) -> InlineKeyboardMarkup:
    kb = []
    for f in features:
        kb.append([_b(f"{f['name']} ({f['price_stars']}⭐)", f"adm:u_feat_grant:{uid}:{f['id']}")])
    kb.append([_b("⬅️ Назад", f"adm:u:{uid}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def billing_kb(mode) -> InlineKeyboardMarkup:
    sub = "✅" if mode.get("subscription_enabled") else "❌"
    ppu = "✅" if mode.get("pay_per_use_enabled") else "❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b(f"{sub} Подписка", "adm:bill_sub")],
        [_b(f"{ppu} Pay-per-use", "adm:bill_ppu")],
        [_b(f"🎁 Бесплатных в день: {mode.get('free_actions_per_day', 0)}", "adm:bill_free")],
        [_b("⬅️ Назад", "adm:back")],
    ])


def prices_kb(prices, action_keys) -> InlineKeyboardMarkup:
    kb = []
    for key, title in action_keys.items():
        price = prices.get(key, 0)
        kb.append([_b(f"{title} — {price}⭐", f"adm:price_act:{key}")])
    kb.append([_b("⬅️ Назад", "adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def balance_kb(uid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("➕ +10⭐", f"adm:bal_add:{uid}:10"), _b("➕ +50⭐", f"adm:bal_add:{uid}:50")],
        [_b("➕ +100⭐", f"adm:bal_add:{uid}:100"), _b("✏️ Своё", f"adm:bal_custom:{uid}")],
        [_b("➖ Обнулить", f"adm:bal_zero:{uid}")],
        [_b("⬅️ К юзеру", f"adm:u:{uid}")],
    ])

def withdrawal_kb(stats, has_history) -> InlineKeyboardMarkup:
    kb = []
    if stats.get("available", 0) > 0:
        kb.append([_b("📝 Записать вывод", "adm:wd_add")])
    if has_history:
        kb.append([_b("📜 История выводов", "adm:wd_history")])
    kb.append([_b("📖 Инструкция", "adm:wd_help")])
    kb.append([_b("⬅️ Назад", "adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def withdrawal_help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("⬅️ Назад", "adm:withdrawal")],
    ])

def bcast_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("👥 Все юзеры", "adm:bcast_do:all")],
        [_b("💎 Только подписчики", "adm:bcast_do:paid")],
        [_b("🆓 Без подписки", "adm:bcast_do:free")],
        [_b("🟢 Активные (7д)", "adm:bcast_do:active7")],
        [_b("💰 С балансом", "adm:bcast_do:with_balance")],
        [_b("⬅️ Назад", "adm:back")],
    ])


def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("👥 Юзеры", "adm:help_u"), _b("💎 Подписки", "adm:help_sub")],
        [_b("🎁 Триал", "adm:help_trial"), _b("💰 Прайс", "adm:help_price")],
        [_b("⚙️ Биллинг", "adm:help_bill"), _b("💵 Цены", "adm:help_cost")],
        [_b("📤 Вывод", "adm:help_wd"), _b("📢 Рассылка", "adm:help_bcast")],
        [_b("⬅️ Назад", "adm:back")],
    ])