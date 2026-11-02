import asyncio
import html
import logging
import re

import yt_dlp
from aiogram import F, Router
from aiogram.types import FSInputFile, Message

from config import MAX_PLAYLIST_TRACKS
from database.cache import get_cached, save_cached
from services.downloader import cleanup, download_audio, _sync_search_dl, TrackMeta
from services.platforms import Platform, detect_platform
from database import postgres_db as db

from services.playlist import parse_spotify_playlist, parse_yandex_album
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
    r"soundcloud\.com/[^/]+/sets/",
    r"[?&]list=",
]

_user_locks: dict = {}


def _get_lock(uid: int) -> asyncio.Lock:
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


def _is_playlist(url: str) -> bool:
    return any(re.search(p, url) for p in PLAYLIST_PATTERNS)


async def _send_audio_safe(message: Message, **kwargs) -> str | None:
    sent = await message.answer_audio(**kwargs)
    if sent and sent.audio:
        return sent.audio.file_id
    return None


async def _process_single(message: Message, url: str, status: Message) -> None:
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
        await status.delete()
    except Exception:
        pass
    cleanup(result.filepath)


async def _process_spotify_playlist(message: Message, url: str, status: Message) -> None:
    playlist = await parse_spotify_playlist(url, max_tracks=MAX_PLAYLIST_TRACKS)
    if not playlist or not playlist.tracks:
        raise RuntimeError(
            "Не удалось разобрать плейлист/альбом Spotify. Возможно, он приватный. "
            "Пришли ссылки на треки по одной."
        )
    total = len(playlist.tracks)
    sent = 0
    for i, track in enumerate(playlist.tracks, 1):
        try:
            await status.edit_text(
                f"📋 <b>{playlist.title}</b>\n"
                f"Скачиваю {i}/{total}: {track.artist} — {track.name}"
            )
            key_url = track.url or f"spotify_search:{track.artist} {track.name}"
            h = url_hash(key_url)
            cached = await get_cached(h)
            if cached:
                await message.answer_audio(
                    audio=cached["file_id"],
                    title=cached["title"] or None,
                    performer=cached["performer"] or None,
                    duration=cached["duration"] or None,
                )
                sent += 1
                continue

            meta = TrackMeta(title=track.name, artist=track.artist, duration=track.duration)
            q = f"ytsearch5:{meta.artist} {meta.title}" if meta.artist else f"ytsearch5:{meta.title}"
            result = await asyncio.to_thread(_sync_search_dl, q, meta, "mp3_320", True)
            audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
            await db.finalize_action(message.from_user.id, "download_track", reason, price)
            try:
                await db.add_download_history(
                    message.from_user.id, url, result.title, result.performer, result.platform, None
                )
            except Exception:
                pass
            file_id = await _send_audio_safe(
                message,
                audio=audio,
                title=result.title or None,
                performer=result.performer or None,
                duration=result.duration or None,
            )
            if file_id:
                await save_cached(h, key_url, "spotify", result.title, result.performer, result.duration, file_id)
            cleanup(result.filepath)
            sent += 1
        except Exception as e:
            logger.exception("playlist track %d failed", i)
            await message.answer(f"❌ {i}. {track.artist} — {track.name}: {html.escape(str(e))[:200]}")
    try:
        await status.edit_text(f"✅ <b>{playlist.title}</b> — готово: {sent}/{total}")
    except Exception:
        pass


def _probe_playlist(url: str) -> dict:
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "noplaylist": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise RuntimeError("yt-dlp не смог обработать эту ссылку")
        return info




async def _process_yandex_playlist(message: Message, url: str, status: Message) -> None:
    playlist = await parse_yandex_album(url, max_tracks=MAX_PLAYLIST_TRACKS)
    if not playlist or not playlist.tracks:
        raise RuntimeError(
            "Не удалось разобрать альбом/плейлист Яндекс.Музыки.\n\n"
            "Возможно, он приватный или содержит только превью."
        )
    total = len(playlist.tracks)
    sent = 0
    for i, track in enumerate(playlist.tracks, 1):
        try:
            await status.edit_text(
                f"📋 <b>{playlist.title}</b>\n"
                f"Скачиваю {i}/{total}: {track.artist} — {track.name}"
            )
            key_url = f"yandex_search:{track.artist} {track.name}"
            h = url_hash(key_url)
            cached = await get_cached(h)
            if cached:
                await message.answer_audio(
                    audio=cached["file_id"],
                    title=cached["title"] or None,
                    performer=cached["performer"] or None,
                    duration=cached["duration"] or None,
                )
                sent += 1
                continue

            meta = TrackMeta(title=track.name, artist=track.artist, duration=track.duration)
            q = f"ytsearch5:{meta.artist} {meta.title}" if meta.artist else f"ytsearch5:{meta.title}"
            result = await asyncio.to_thread(_sync_search_dl, q, meta, "mp3_320", True)
            audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
            file_id = await _send_audio_safe(
                message,
                audio=audio,
                title=result.title or None,
                performer=result.performer or None,
                duration=result.duration or None,
            )
            if file_id:
                await save_cached(h, key_url, "yandex", result.title, result.performer, result.duration, file_id)
            cleanup(result.filepath)
            sent += 1
        except Exception as e:
            logger.exception("yandex playlist track %d failed", i)
            await message.answer(f"❌ {i}. {track.artist} — {track.name}: {html.escape(str(e))[:200]}")
    try:
        await status.edit_text(f"✅ <b>{playlist.title}</b> — готово: {sent}/{total}")
    except Exception:
        pass


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
                f"📋 <b>{title}</b>\n"
                f"Скачиваю {i}/{total}: {entry.get('title', '?')}"
            )
            track_url = entry.get("webpage_url") or entry["url"]
            h = url_hash(track_url)
            cached = await get_cached(h)
            if cached:
                await message.answer_audio(
                    audio=cached["file_id"],
                    title=cached["title"] or None,
                    performer=cached["performer"] or None,
                    duration=cached["duration"] or None,
                )
                sent += 1
                continue
            result = await download_audio(track_url)
            audio = FSInputFile(str(result.filepath), filename=result.filepath.name)
            await db.finalize_action(message.from_user.id, "download_track", reason, price)
            try:
                await db.add_download_history(
                    message.from_user.id, url, result.title, result.performer, result.platform, None
                )
            except Exception:
                pass
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
            await message.answer(f"❌ {i}. {entry.get('title', '?')}: {html.escape(str(e))[:200]}")
    try:
        await status.edit_text(f"✅ <b>{title}</b> — готово: {sent}/{total}")
    except Exception:
        pass


@router.message(F.text.regexp(r"^https?://\S+"))
async def handle_url(message: Message) -> None:
    url = message.text.strip()
    platform = detect_platform(url)

    if platform == Platform.UNKNOWN:
        await message.answer(
            "❌ Неизвестная платформа.\n"
            "Поддерживаются: Spotify, SoundCloud, Яндекс.Музыка, YouTube, Bandcamp, VK."
        )
        return

    # Pay-per-use: проверка доступа БЕЗ списания
    ok, reason, price, balance = await db.check_action_access(
        message.from_user.id, "download_track"
    )
    if not ok:
        if reason == "need_topup":
            await message.answer(
                f"💳 <b>Недостаточно средств</b>\n\n"
                f"Стоимость: <b>{price}⭐</b>\n"
                f"Твой баланс: <b>{balance}⭐</b>\n"
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

    lock = _get_lock(message.from_user.id)
    if lock.locked():
        await message.answer("⏳ Уже идёт обработка. Дождись.")
        return

    async with lock:
        label = PLATFORM_LABEL.get(platform, platform.value)
        status = await message.answer(f"⏳ Обрабатываю {label}...")
        try:
            if _is_playlist(url):
                if platform == Platform.SPOTIFY:
                    await _process_spotify_playlist(message, url, status)
                elif platform == Platform.YANDEX:
                    # Сначала yt-dlp (умеет YandexMusic extractor), fallback на HTML
                    try:
                        await _process_ytdlp_playlist(message, url, status)
                    except Exception as e:
                        logger.warning("yandex yt-dlp failed: %s, fallback HTML", e)
                        await _process_yandex_playlist(message, url, status)
                else:
                    await _process_ytdlp_playlist(message, url, status)
            else:
                await _process_single(message, url, status)
        except Exception as e:
            logger.exception("handle_url failed")
            safe = html.escape(str(e))[:500]
            try:
                await status.edit_text(f"❌ Не удалось скачать: {safe}")
            except Exception:
                try:
                    await message.answer(f"❌ {safe}", parse_mode=None)
                except Exception:
                    pass