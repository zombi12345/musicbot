from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)