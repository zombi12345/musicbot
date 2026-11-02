from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Снизу — только Меню + Админ (админам)."""
    kb = [[KeyboardButton(text="🏠 Меню")]]
    if is_admin:
        kb.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def main_inline(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Все функции — красивая сетка 2 колонки."""
    kb = [
        [InlineKeyboardButton(text="🎵 Скачать трек", callback_data="user:menu_download"),
         InlineKeyboardButton(text="🎤 Распознать", callback_data="user:menu_recognize")],
        [InlineKeyboardButton(text="📋 Плейлист", callback_data="user:menu_playlist"),
         InlineKeyboardButton(text="📝 Текст песни", callback_data="user:menu_lyrics")],
        [InlineKeyboardButton(text="📊 Профиль", callback_data="user:menu_profile"),
         InlineKeyboardButton(text="💎 Подписка", callback_data="user:menu_sub")],
        [InlineKeyboardButton(text="💳 Баланс", callback_data="user:menu_balance"),
         InlineKeyboardButton(text="🎁 Триал", callback_data="user:menu_trial")],
        [InlineKeyboardButton(text="💡 Как работает", callback_data="user:menu_howto"),
         InlineKeyboardButton(text="❓ Помощь", callback_data="user:help")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def sub_inline(pricing, subscription_enabled: bool) -> InlineKeyboardMarkup:
    """Тарифы подписки — по одной кнопке в ряд (крупные)."""
    kb = []
    if subscription_enabled:
        for key in ["7", "30", "90"]:
            if key in pricing:
                info = pricing[key]
                kb.append([
                    InlineKeyboardButton(
                        text=f"💎 {info['days']} дней — {info['stars']}⭐",
                        callback_data=f"pay:sub:{key}",
                    )
                ])
    kb.append([InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="user:menu_balance")])
    kb.append([InlineKeyboardButton(text="🎁 Активировать триал", callback_data="user:trial")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="user:menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def balance_inline() -> InlineKeyboardMarkup:
    """Пакеты пополнения — 2 колонки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ 50⭐", callback_data="pay:balance:50"),
         InlineKeyboardButton(text="➕ 100⭐", callback_data="pay:balance:100")],
        [InlineKeyboardButton(text="➕ 250⭐", callback_data="pay:balance:250"),
         InlineKeyboardButton(text="➕ 500⭐", callback_data="pay:balance:500")],
        [InlineKeyboardButton(text="💎 Подписка (безлимит)", callback_data="user:menu_sub")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="user:menu")],
    ])


def help_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Как скачать", callback_data="user:help_download")],
        [InlineKeyboardButton(text="🎤 Как распознать", callback_data="user:help_recognize")],
        [InlineKeyboardButton(text="💎 Подписка vs Баланс", callback_data="user:help_billing")],
        [InlineKeyboardButton(text="💳 Как пополнить", callback_data="user:help_buy")],
        [InlineKeyboardButton(text="🆘 Проблемы", callback_data="user:help_troubleshoot")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="user:menu")],
    ])


def back_to_help() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К помощи", callback_data="user:help")],
    ])


def cancel_kb(callback: str = "user:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=callback)],
    ])


def recognize_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="user:recognize_cancel")],
    ])


def lyrics_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="user:lyrics_cancel")],
    ])


def tracks_inline(has_tracks: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="user:menu")],
    ])