"""Скачивание аудио через yt-dlp + метаданные через mutagen.

Платформы:
  - SoundCloud, YouTube  -> прямой yt-dlp
  - Яндекс.Музыка        -> пробуем прямой yt-dlp (часто работает)
  - Spotify              -> oEmbed -> yt-dlp ytsearch1
"""
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import yt_dlp
from dotenv import load_dotenv
from mutagen.id3 import ID3, TIT2, TPE1
from mutagen.mp3 import MP3

from services.platforms import Platform, detect_platform

load_dotenv()

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

SPOTIFY_OEMBED = "https://open.spotify.com/oembed"
FFMPEG_LOCATION = os.getenv("FFMPEG_LOCATION", "").strip() or None


@dataclass
class DownloadResult:
    filepath: Path
    title: str
    performer: str
    duration: int = 0
    platform: str = "unknown"


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def _sync_ytdlp(url: str, audio_format: str = "mp3_320") -> DownloadResult:
    """Синхронная загрузка yt-dlp (запускается в потоке)."""
    outtmpl = str(DOWNLOAD_DIR / "%(title).80s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "auto",
    }
    if FFMPEG_LOCATION:
        ydl_opts["ffmpeg_location"] = FFMPEG_LOCATION
    ydl_opts["postprocessors"] = [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "320" if audio_format == "mp3_320" else "192",
    }]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("yt-dlp вернул None")
        if "entries" in info:
            info = info["entries"][0]
        filepath = Path(ydl.prepare_filename(info)).with_suffix(".mp3")

    title = info.get("title") or "Unknown"
    performer = info.get("uploader") or info.get("artist") or "Unknown"
    duration = int(info.get("duration") or 0)

    try:
        audio = MP3(str(filepath))
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=performer))
        audio.save()
    except Exception as e:
        logger.warning("Не удалось встроить теги: %s", e)

    return DownloadResult(
        filepath=filepath,
        title=title,
        performer=performer,
        duration=duration,
    )


async def _spotify_metadata(url: str) -> tuple[str, str]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(SPOTIFY_OEMBED, params={"url": url})
            r.raise_for_status()
            data = r.json()
        return (data.get("title", "").strip(), "")
    except Exception as e:
        logger.warning("Spotify oEmbed failed: %s", e)
        return ("", "")


async def _download_spotify(url: str, audio_format: str) -> DownloadResult:
    title, _ = await _spotify_metadata(url)
    if not title:
        raise RuntimeError("Не удалось получить метаданные Spotify")
    search_query = f"ytsearch1:{title} audio"
    result = await asyncio.to_thread(_sync_ytdlp, search_query, audio_format)
    result.platform = "spotify"
    return result


async def download_audio(url: str, audio_format: str = "mp3_320") -> DownloadResult:
    platform = detect_platform(url)

    if platform == Platform.SPOTIFY:
        return await _download_spotify(url, audio_format)

    if platform in (Platform.SOUNDCLOUD, Platform.YOUTUBE, Platform.YANDEX):
        try:
            result = await asyncio.to_thread(_sync_ytdlp, url, audio_format)
            result.platform = platform.value
            return result
        except Exception as e:
            logger.warning("Прямое скачивание %s упало: %s", platform.value, e)
            if platform == Platform.YANDEX:
                raise RuntimeError(
                    "Яндекс.Музыка требует авторизации. "
                    "Пришли ссылку на тот же трек в SoundCloud или YouTube."
                )
            raise

    raise RuntimeError(f"Платформа не поддерживается: {platform.value}")


def cleanup(path: Path) -> None:
    try:
        if path and path.exists():
            path.unlink()
    except Exception as e:
        logger.warning("cleanup failed: %s", e)