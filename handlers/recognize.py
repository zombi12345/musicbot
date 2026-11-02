import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from aiogram import F, Router
from aiogram.types import FSInputFile, Message

from database import postgres_db as db
from services.downloader import _sync_search_dl, TrackMeta, cleanup
from services.recognize import recognize_file
from utils.checks import is_banned

router = Router(name="recognize")
logger = logging.getLogger(__name__)

_user_locks: dict = {}


def _get_lock(uid: int) -> asyncio.Lock:
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


@router.message(F.text == "🎤 Распознать музыку")
async def btn_recognize(message: Message) -> None:
    await message.answer(
        "🎤 Пришли голосовое, аудио или видео (5-15 сек достаточно) — "
        "я попробую распознать трек и скачать его."
    )


@router.message(F.voice | F.audio | F.video_note | F.video)
async def handle_voice(message: Message) -> None:
    if await is_banned(message.from_user.id):
        await message.answer("⛔ Вы заблокированы.")
        return

    lock = _get_lock(message.from_user.id)
    if lock.locked():
        await message.answer("⏳ Уже слушаю. Дождись.")
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
                    f"Баланс: <b>{balance}⭐</b>\n"
                    f"Не хватает: <b>{price - balance}⭐</b>\n\n"
                    f"Пополнить: /balance"
                )
            else:
                await message.answer(
                    "❌ <b>Нет доступа</b>\n\n"
                    "• 💎 Подписка: /sub\n"
                    "• 🎁 Триал: /trial\n"
                    "• 💳 Баланс: /balance"
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
                tg_file_info = message.voice
            elif message.audio:
                tg_file_info = message.audio
            elif message.video_note:
                tg_file_info = message.video_note
            else:
                tg_file_info = message.video

            tg_file = await message.bot.get_file(tg_file_info.file_id)
            await message.bot.download_file(tg_file.file_path, destination=str(tmp_path))

            info = await recognize_file(tmp_path)
            if not info or not info.get("title"):
                await status.edit_text(
                    "❌ Не удалось распознать.\n\n"
                    "💳 Списание НЕ произведено."
                )
                return

            title = info["title"]
            artist = info.get("artist", "")
            await status.edit_text(f"🔍 Нашёл: {artist} — {title}\n⏳ Скачиваю...")

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
            logger.exception("recognize handler failed")
            try:
                await status.edit_text(f"❌ Ошибка: {e}\n\n💳 Списание НЕ произведено.")
            except Exception:
                pass
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass