import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from database import postgres_db as db
from keyboards.main import main_menu, recognize_kb
from services.downloader import _sync_search_dl, TrackMeta, cleanup
from services.recognize import recognize_file
from states import RecognizeStates
from utils.checks import is_admin, is_banned

router = Router(name="recognize")
logger = logging.getLogger(__name__)

_user_locks: dict = {}


def _get_lock(uid: int) -> asyncio.Lock:
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


@router.message(F.text == "🎤 Распознать")
async def btn_recognize(message: Message, state: FSMContext) -> None:
    if await is_banned(message.from_user.id):
        return
    await state.set_state(RecognizeStates.waiting_voice)
    await message.answer(
        "🎤 <b>Распознать музыку</b>\n\n"
        "🔴 <b>Жду голосовое сообщение</b>\n\n"
        "Запиши фрагмент 10-15 секунд и отправь сюда.\n\n"
        "💡 <b>Советы:</b>\n"
        "  • Минимум 10 секунд\n"
        "  • Ближе к источнику звука\n"
        "  • Лучше слышны слова\n\n"
        "💳 <i>Если не распознаю — деньги не спишутся</i>",
        reply_markup=recognize_kb(),
    )


@router.callback_query(F.data == "user:recognize_cancel")
async def cb_recognize_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await call.message.edit_text("❌ Распознавание отменено.")
    except Exception:
        pass
    admin = await is_admin(call.from_user.id)
    await call.message.answer(
        "🏠 <b>Главное меню</b> — кнопки внизу",
        reply_markup=main_menu(is_admin=admin),
    )
    await call.answer()


@router.message(RecognizeStates.waiting_voice, F.voice | F.audio | F.video_note | F.video)
async def handle_voice_in_state(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _process_voice(message)


@router.message(F.voice | F.audio | F.video_note | F.video)
async def handle_voice_free(message: Message, state: FSMContext) -> None:
    # Если голосовое без команды — тоже обрабатываем
    await state.clear()
    await _process_voice(message)


async def _process_voice(message: Message) -> None:
    if await is_banned(message.from_user.id):
        return

    lock = _get_lock(message.from_user.id)
    if lock.locked():
        await message.answer("⏳ Уже слушаю предыдущее. Подожди.")
        return

    async with lock:
        ok, reason, price, balance = await db.check_action_access(
            message.from_user.id, "recognize"
        )
        if not ok:
            if reason == "need_topup":
                await message.answer(
                    f"💳 <b>Недостаточно средств</b>\n\n"
                    f"Распознавание: <b>{price}⭐</b>\n"
                    f"Баланс: <b>{balance}⭐</b>\n\n"
                    f"Пополнить: /buy"
                )
            else:
                await message.answer(
                    "❌ <b>Нет доступа</b>\n\n"
                    "• 💎 Подписка: /sub\n"
                    "• 🎁 Триал: /trial\n"
                    "• 💳 Баланс: /buy"
                )
            return

        status = await message.answer("🎧 Слушаю...")
        tmp_dir = Path("downloads")
        tmp_dir.mkdir(exist_ok=True)
        suffix = ".ogg"
        if message.audio and message.audio.file_name:
            suffix = Path(message.audio.file_name).suffix or ".mp3"
        elif message.video or message.video_note:
            suffix = ".mp4"
        tmp_path = tmp_dir / f"recognize_{uuid4().hex}{suffix}"

        try:
            if message.voice:
                info_tg = message.voice
            elif message.audio:
                info_tg = message.audio
            elif message.video_note:
                info_tg = message.video_note
            else:
                info_tg = message.video

            tg_file = await message.bot.get_file(info_tg.file_id)
            await message.bot.download_file(tg_file.file_path, destination=str(tmp_path))

            info = await recognize_file(tmp_path)
            if not info or not info.get("title"):
                await status.edit_text(
                    "❌ <b>Не удалось распознать</b>\n\n"
                    "Попробуй:\n"
                    "  • Длинее (10-15 сек)\n"
                    "  • Ближе к звуку\n"
                    "  • Другой фрагмент\n\n"
                    "💳 <i>Деньги НЕ списаны</i>"
                )
                return

            title = info["title"]
            artist = info.get("artist", "")
            await status.edit_text(f"🔍 Нашёл: <b>{artist} — {title}</b>\n⏳ Скачиваю...")

            meta = TrackMeta(title=title, artist=artist)
            q = f"ytsearch5:{artist} {title}" if artist else f"ytsearch5:{title}"
            result = await asyncio.to_thread(_sync_search_dl, q, meta, "mp3_320", False)

            new_bal = await db.finalize_action(message.from_user.id, "recognize", reason, price)

            audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
            await message.answer_audio(
                audio=audio,
                title=result.title or title,
                performer=result.performer or artist,
                duration=result.duration or None,
            )
            try:
                await status.delete()
            except Exception:
                pass

            if reason == "pay_per_use" and price > 0:
                try:
                    await message.answer(f"💳 -{price}⭐ · Баланс: {new_bal}⭐")
                except Exception:
                    pass

            cleanup(result.filepath)
        except Exception as e:
            logger.exception("recognize failed")
            try:
                await status.edit_text(f"❌ Ошибка: {e}\n\n💳 <i>Деньги НЕ списаны</i>")
            except Exception:
                pass
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass