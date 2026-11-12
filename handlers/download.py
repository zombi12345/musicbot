import asyncio
import html
import logging
import re

import yt_dlp
from aiogram import F, Router
from aiogram.types import FSInputFile, Message

import config
from config import MAX_PLAYLIST_TRACKS
from database import postgres_db as db
from database.cache import get_cached, save_cached
from services.downloader import (
    TrackMeta,
    _sync_search_dl,
    cleanup,
    download_audio,
)
from services.platforms import Platform, detect_platform
from services.playlist import (
    parse_spotify_playlist,
    parse_soundcloud_playlist,
    parse_yandex_album,
)
from utils.urls import url_hash

router = Router(name="download")
logger = logging.getLogger(__name__)

PLATFORM_LABEL = {
    Platform.SPOTIFY: "Spotify",
    Platform.SOUNDCLOUD: "SoundCloud",
    Platform.YANDEX: "Яндекс.Музыка",
    Platform.YOUTUBE: "YouTube",
}

PLAYLIST_PATTERNS = [
    r"/playlist/",
    r"/album/",
    r"on\.soundcloud\.com/",
    r"soundcloud\.com/[^/]+/sets/",
    r"[?&]list=",
]

_user_locks: dict = {}


def _get_lock(uid: int) -> asyncio.Lock:
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


def _is_playlist(url: str) -> bool:
    # Yandex: /album/ID/track/ID → single track
    if re.search(r"/album/\d+/track/\d+", url):
        return False
    # Spotify: /track/ID → single track
    if "spotify.com" in url and re.search(r"/track/[a-zA-Z0-9]+", url):
        return False
    # SoundCloud sets → playlist
    if "soundcloud.com" in url and "/sets/" in url:
        return True
    return any(re.search(p, url) for p in PLAYLIST_PATTERNS)


async def _send_audio_safe(message: Message, **kwargs):
    sent = await message.answer_audio(**kwargs)
    if sent and sent.audio:
        return sent.audio.file_id
    return None


# ============================================================
# SINGLE TRACK
# ============================================================

async def _process_single(message: Message, url: str, status: Message) -> None:
    uid = message.from_user.id
    h = url_hash(url)
    cached = await get_cached(h)
    if cached:
        logger.info("cache hit %s", h)
        try:
            await message.answer_audio(
                audio=cached["file_id"],
                title=cached["title"] or None,
                performer=cached["performer"] or None,
                duration=cached["duration"] or None,
            )
            await status.delete()
            return
        except Exception as e:
            logger.warning("cache send failed: %s", e)

    result = await download_audio(url)
    audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
    file_id = await _send_audio_safe(
        message,
        audio=audio,
        title=result.title or None,
        performer=result.performer or None,
        duration=result.duration or None,
    )
    if file_id:
        await save_cached(h, url, result.platform, result.title, result.performer, result.duration, file_id)
        try:
            await db.add_download_history(
                uid, url, result.title, result.performer, result.platform, None
            )
        except Exception:
            pass
    try:
        await status.delete()
    except Exception:
        pass
    cleanup(result.filepath)


# ============================================================
# PLAYLISTS (free, no finalize)
# ============================================================

async def _send_playlist_track(message: Message, i: int, total: int, track) -> bool:
    """Скачивает один трек. True если отправлен."""
    key_url = track.url or f"search:{track.artist} {track.name}"
    h = url_hash(key_url)
    cached = await get_cached(h)
    if cached:
        try:
            await message.answer_audio(
                audio=cached["file_id"],
                title=cached["title"] or None,
                performer=cached["performer"] or None,
                duration=cached["duration"] or None,
            )
            return True
        except Exception as e:
            logger.warning("cache send failed: %s", e)

    meta = TrackMeta(title=track.name, artist=track.artist, duration=track.duration)

    # Попытка 1: YouTube
    try:
        q = f"ytsearch5:{meta.artist} {meta.title}" if meta.artist else f"ytsearch5:{meta.title}"
        result = await asyncio.to_thread(_sync_search_dl, q, meta, "mp3_320", True, True)
        audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
        file_id = await _send_audio_safe(
            message,
            audio=audio,
            title=result.title or None,
            performer=result.performer or None,
            duration=result.duration or None,
        )
        if file_id:
            await save_cached(h, key_url, "playlist_yt", result.title, result.performer, result.duration, file_id)
        cleanup(result.filepath)
        return True
    except Exception as e1:
        logger.info("YT failed [%s - %s], trying SoundCloud: %s",
                    meta.artist, meta.title, str(e1)[:80])

    # Попытка 2: SoundCloud
    try:
        q = f"scsearch3:{meta.artist} {meta.title}" if meta.artist else f"scsearch3:{meta.title}"
        result = await asyncio.to_thread(_sync_search_dl, q, meta, "mp3_320", False, True)
        audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
        file_id = await _send_audio_safe(
            message,
            audio=audio,
            title=result.title or None,
            performer=result.performer or None,
            duration=result.duration or None,
        )
        if file_id:
            await save_cached(h, key_url, "playlist_sc", result.title, result.performer, result.duration, file_id)
        cleanup(result.filepath)
        logger.info("SC success: %s - %s", meta.artist, meta.title)
        return True
    except Exception as e2:
        logger.warning("SC also failed [%s]: %s", track.name, str(e2)[:80])
        try:
            await message.answer(
                f"❌ {i}. {html.escape(str(track.artist or ''))} — {html.escape(str(track.name))}\n"
                f"<i>Не нашёл ни на YouTube, ни на SoundCloud</i>"
            )
        except Exception:
            pass
        return False



async def _process_parsed_playlist(message: Message, playlist, status: Message, concurrency: int = 2) -> None:
    """Параллельное скачивание по 2-3 трека."""
    if not playlist or not getattr(playlist, "tracks", None):
        raise RuntimeError("Пустой плейлист")
    total = len(playlist.tracks)
    sem = asyncio.Semaphore(concurrency)
    counter = {"sent": 0, "done": 0}
    lock = asyncio.Lock()

    async def worker(i: int, track):
        async with sem:
            ok = await _send_playlist_track(message, i, total, track)
            async with lock:
                counter["done"] += 1
                if ok:
                    counter["sent"] += 1
                try:
                    await status.edit_text(
                        f"📋 <b>{html.escape(playlist.title)}</b>\n"
                        f"Готово: {counter['done']}/{total} (✅ {counter['sent']})\n"
                        f"<i>Параллельно: {concurrency}</i>"
                    )
                except Exception:
                    pass
            return ok

    tasks = [worker(i, t) for i, t in enumerate(playlist.tracks, 1)]
    await asyncio.gather(*tasks, return_exceptions=True)

    try:
        await status.edit_text(
            f"✅ <b>{html.escape(playlist.title)}</b>\n"
            f"Готово: {counter['sent']}/{total}"
        )
    except Exception:
        pass

        if await _send_playlist_track(message, i, total, track):
            sent += 1
    try:
        await status.edit_text(f"✅ <b>{html.escape(playlist.title)}</b>\nГотово: {sent}/{total}")
    except Exception:
        pass


def _probe_playlist(url: str) -> dict:
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "noplaylist": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise RuntimeError("yt-dlp не смог обработать ссылку")
        return info


async def _process_ytdlp_playlist(message: Message, url: str, status: Message) -> None:
    try:
        info = await asyncio.to_thread(_probe_playlist, url)
    except Exception as e:
        raise RuntimeError(f"Не удалось разобрать плейлист: {e}")
    entries = [e for e in (info.get("entries") or []) if e and e.get("url")]
    entries = entries[:MAX_PLAYLIST_TRACKS]
    if not entries:
        raise RuntimeError("Плейлист пуст или недоступен")
    total = len(entries)
    title = info.get("title") or "Playlist"
    sent = 0
    for i, entry in enumerate(entries, 1):
        try:
            await status.edit_text(
                f"📋 <b>{html.escape(str(title)[:100])}</b>\n"
                f"Скачиваю {i}/{total}\n"
                f"<i>{html.escape(str(entry.get('title', '?'))[:100])}</i>"
            )
        except Exception:
            pass
        track_url = entry.get("webpage_url") or entry["url"]
        h = url_hash(track_url)
        cached = await get_cached(h)
        if cached:
            try:
                await message.answer_audio(
                    audio=cached["file_id"],
                    title=cached["title"] or None,
                    performer=cached["performer"] or None,
                    duration=cached["duration"] or None,
                )
                sent += 1
            except Exception:
                pass
            continue
        try:
            result = await download_audio(track_url)
            audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
            file_id = await _send_audio_safe(
                message,
                audio=audio,
                title=result.title or None,
                performer=result.performer or None,
                duration=result.duration or None,
            )
            if file_id:
                await save_cached(h, track_url, result.platform, result.title, result.performer, result.duration, file_id)
            cleanup(result.filepath)
            sent += 1
        except Exception as e:
            logger.exception("ytdlp playlist track %d failed", i)
            try:
                await message.answer(f"❌ {i}. {html.escape(str(e))[:100]}")
            except Exception:
                pass
    try:
        await status.edit_text(f"✅ <b>{html.escape(str(title)[:100])}</b>\nГотово: {sent}/{total}")
    except Exception:
        pass


# ============================================================
# MAIN HANDLER
# ============================================================

@router.message(F.text.regexp(r"^https?://\S+"))
async def handle_url(message: Message) -> None:
    url = message.text.strip()
    platform = detect_platform(url)

    if platform == Platform.UNKNOWN:
        await message.answer(
            "❌ Неизвестная платформа.\n"
            "Поддерживаются: Spotify, SoundCloud, Яндекс, YouTube, Bandcamp, VK."
        )
        return

    uid = message.from_user.id
    lock = _get_lock(uid)
    if lock.locked():
        await message.answer("⏳ Уже идёт обработка. Дождись.")
        return

    async with lock:
        is_pl = _is_playlist(url)
        label = PLATFORM_LABEL.get(platform, platform.value)

        # Pay-per-use: только для одиночных треков
        reason = "free_mode"
        price = 0
        if not is_pl:
            ok, reason, price, balance = await db.check_action_access(uid, "download_track")
            if not ok:
                if reason == "need_topup":
                    await message.answer(
                        f"💳 <b>Недостаточно средств</b>\n\n"
                        f"Стоимость: <b>{price}⭐</b>\n"
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

        action = "плейлист" if is_pl else "трек"
        status = await message.answer(f"⏳ Обрабатываю {action} с {label}...")

        try:
            if is_pl:
                if platform == Platform.SPOTIFY:
                    playlist = await parse_spotify_playlist(url, max_tracks=MAX_PLAYLIST_TRACKS)
                    if not playlist:
                        raise RuntimeError(
                            "Не удалось найти альбом на Deezer.\n"
                            "Пришли ссылки на треки по одной."
                        )
                    await _process_parsed_playlist(message, playlist, status)
                elif platform == Platform.YANDEX:
                    playlist = await parse_yandex_album(url, max_tracks=MAX_PLAYLIST_TRACKS)
                    if not playlist:
                        # Fallback: yt-dlp напрямую
                        await _process_ytdlp_playlist(message, url, status)
                    else:
                        await _process_parsed_playlist(message, playlist, status)
                elif platform == Platform.SOUNDCLOUD:
                    resolved = await parse_soundcloud_playlist(url, max_tracks=MAX_PLAYLIST_TRACKS)
                    target = (resolved or {}).get("resolved_url") or url
                    logger.info("soundcloud target: %s", target)
                    await _process_ytdlp_playlist(message, target, status)
                else:
                    await _process_ytdlp_playlist(message, url, status)
            else:
                await _process_single(message, url, status)
                # Финализация оплаты ТОЛЬКО после успешного одиночного скачивания
                try:
                    await db.finalize_action(uid, "download_track", reason, price)
                except Exception:
                    pass
        except Exception as e:
            logger.exception("handle_url failed")
            safe = html.escape(str(e))[:500]
            try:
                await status.edit_text(f"❌ {safe}")
            except Exception:
                try:
                    await message.answer(f"❌ {safe}", parse_mode=None)
                except Exception:
                    pass