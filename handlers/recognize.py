import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from aiogram import F, Router
from aiogram.types import FSInputFile, Message

from services.downloader import _sync_search_dl, TrackMeta, cleanup
from services.recognize import recognize_file

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
    lock = _get_lock(message.from_user.id)
    if lock.locked():
        await message.answer("⏳ Уже слушаю. Дождись.")
        return

    async with lock:
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
                    "❌ Не удалось распознать. Попробуй фрагмент подлиннее (10-15 сек) "
                    "или пришли ссылку на трек."
                )
                return

            title = info["title"]
            artist = info.get("artist", "")
            await status.edit_text(f"🔍 Нашёл: {artist} — {title}\n⏳ Скачиваю...")

            meta = TrackMeta(title=title, artist=artist)
            q = f"ytsearch5:{artist} {title}" if artist else f"ytsearch5:{title}"
            result = await asyncio.to_thread(_sync_search_dl, q, meta, "mp3_320", False)
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
            cleanup(result.filepath)
        except Exception as e:
            logger.exception("recognize handler failed")
            try:
                await status.edit_text(f"❌ Ошибка: {e}")
            except Exception:
                pass
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass