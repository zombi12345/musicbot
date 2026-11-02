from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🎵 Скачать трек")],
        [KeyboardButton(text="🎤 Распознать музыку")],
        [
            KeyboardButton(text="📊 Мой профиль"),
            KeyboardButton(text="❓ Помощь"),
        ],
    ]
    if is_admin:
        kb.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)