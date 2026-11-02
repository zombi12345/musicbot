from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🎵 Скачать трек")],
        [KeyboardButton(text="🎤 Распознать музыку")],
        [
            KeyboardButton(text="📊 Мой профиль"),
            KeyboardButton(text="❓ Помощь"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)