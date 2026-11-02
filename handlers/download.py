import asyncio
import logging

from aiogram import F, Router
from aiogram.types import FSInputFile, Message

from services.downloader import cleanup, download_audio
from services.platforms import Platform, detect_platform

router = Router(name="download")
logger = logging.getLogger(__name__)

PLATFORM_LABEL = {
    Platform.SPOTIFY: "Spotify",
    Platform.SOUNDCLOUD: "SoundCloud",
    Platform.YANDEX: "Яндекс.Музыка",
    Platform.YOUTUBE: "YouTube",
}

_user_locks: dict[int, asyncio.Lock] = {}


def _get_lock(uid: int) -> asyncio.Lock:
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


@router.message(F.text.regexp(r"^https?://\S+"))
async def handle_url(message: Message) -> None:
    url = message.text.strip()
    platform = detect_platform(url)

    if platform == Platform.UNKNOWN:
        await message.answer(
            "❌ Неизвестная платформа.\n"
            "Поддерживаются: Spotify, SoundCloud, Яндекс.Музыка, YouTube."
        )
        return

    lock = _get_lock(message.from_user.id)
    if lock.locked():
        await message.answer("⏳ У тебя уже идёт скачивание. Дождись.")
        return

    async with lock:
        label = PLATFORM_LABEL.get(platform, platform.value)
        status = await message.answer(f"⏳ Скачиваю с {label}...")
        result = None
        try:
            result = await download_audio(url)
            audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
            await message.answer_audio(
                audio=audio,
                title=result.title or None,
                performer=result.performer or None,
                duration=result.duration or None,
            )
            try:
                await status.delete()
            except Exception:
                pass
        except Exception as e:
            logger.exception("download error")
            await status.edit_text(f"❌ Не удалось скачать: {e}")
        finally:
            if result and result.filepath:
                cleanup(result.filepath)