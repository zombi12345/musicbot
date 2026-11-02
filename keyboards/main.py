from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🎵 Скачать трек"), KeyboardButton(text="🎤 Распознать")],
        [KeyboardButton(text="📋 Плейлист"), KeyboardButton(text="📝 Текст песни")],
        [KeyboardButton(text="📜 Мои треки"), KeyboardButton(text="📊 Профиль")],
        [KeyboardButton(text="💎 Подписка"), KeyboardButton(text="💳 Баланс")],
        [KeyboardButton(text="🎁 Триал"), KeyboardButton(text="💡 Как работает")],
        [KeyboardButton(text="❓ Помощь")],
    ]
    if is_admin:
        kb.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def sub_inline(pricing, subscription_enabled: bool) -> InlineKeyboardMarkup:
    kb = []
    if subscription_enabled:
        for key in ["7", "30", "90"]:
            if key in pricing:
                info = pricing[key]
                kb.append([
                    InlineKeyboardButton(
                        text=f"💎 {info['days']} дней — {info['stars']}⭐",
                        callback_data=f"user:sub:{key}",
                    )
                ])
    kb.append([InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="user:buy")])
    kb.append([InlineKeyboardButton(text="🎁 Активировать триал", callback_data="user:trial")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def help_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Как скачать", callback_data="user:help_download")],
        [InlineKeyboardButton(text="🎤 Как распознать", callback_data="user:help_recognize")],
        [InlineKeyboardButton(text="📋 Плейлисты", callback_data="user:help_playlist")],
        [InlineKeyboardButton(text="📝 Текст песни", callback_data="user:help_lyrics")],
        [InlineKeyboardButton(text="💎 Подписка vs Баланс", callback_data="user:help_billing")],
        [InlineKeyboardButton(text="💳 Как пополнить", callback_data="user:help_buy")],
        [InlineKeyboardButton(text="🆘 Проблемы", callback_data="user:help_troubleshoot")],
    ])


def back_to_help() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К помощи", callback_data="user:help")],
    ])


def tracks_inline(has_tracks: bool) -> InlineKeyboardMarkup:
    kb = []
    if has_tracks:
        kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="user:tracks_refresh")])
    kb.append([InlineKeyboardButton(text="🎵 Скачать ещё", callback_data="user:hint_download")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def lyrics_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="user:lyrics_cancel")],
    ])