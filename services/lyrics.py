"""Текст песен: lrclib.net + lyrics.ovh + meta из URL."""
import asyncio
import json
import logging
import re
import urllib.parse
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

LRCLIB_URL = "https://lrclib.net/api/get"
LYRICS_OVH_URL = "https://api.lyrics.ovh/v1/{artist}/{title}"
UA = "MusicBot/1.0"


def _clean_timestamps(text: str) -> str:
    """Убирает [MM:SS.ms] из synced lyrics."""
    return re.sub(r"\[\d{1,3}:\d{2}(?:\.\d+)?\]\s*", "", text)


def clean_lyrics(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


async def _try_lrclib(artist: str, title: str) -> Optional[str]:
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}) as c:
                r = await c.get(
                    LRCLIB_URL,
                    params={"artist_name": artist, "track_name": title},
                )
                if r.status_code == 200:
                    data = r.json()
                    plain = data.get("plainLyrics")
                    if plain:
                        return plain
                    synced = data.get("syncedLyrics")
                    if synced:
                        return _clean_timestamps(synced)
                    return None
                if r.status_code in (502, 503, 504) and attempt < 2:
                    await asyncio.sleep(1.5)
                    continue
                return None
        except Exception:
            logger.warning("lrclib attempt %d failed", attempt + 1)
            if attempt < 2:
                await asyncio.sleep(1.5)
    return None


async def _try_lyrics_ovh(artist: str, title: str) -> Optional[str]:
    try:
        a = urllib.parse.quote(artist)
        t = urllib.parse.quote(title)
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(LYRICS_OVH_URL.format(artist=a, title=t))
            if r.status_code == 200:
                return r.json().get("lyrics")
    except Exception:
        logger.warning("lyrics.ovh failed")
    return None


async def fetch_lyrics(artist: str, title: str) -> Optional[dict]:
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not title:
        return None

    text = await _try_lrclib(artist, title)
    if text:
        return {"source": "lrclib", "lyrics": text}

    text = await _try_lyrics_ovh(artist, title)
    if text:
        return {"source": "lyrics.ovh", "lyrics": text}

    return None


async def extract_meta_from_url(url: str) -> Optional[tuple]:
    """Возвращает (artist, title) из URL или None."""
    # ==== Spotify ====
    if "spotify.com" in url:
        m = re.search(r"/track/([a-zA-Z0-9]+)", url)
        if not m:
            return None  # только треки поддерживаем для lyrics
        sid = m.group(1)
        title = ""
        artist = ""
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
                r = await c.get("https://open.spotify.com/oembed", params={"url": url})
                if r.status_code == 200:
                    title = r.json().get("title", "")
                r2 = await c.get(f"https://open.spotify.com/embed/track/{sid}")
                if r2.status_code == 200:
                    mt = re.search(r'"subtitle"\s*:\s*"((?:[^"\\]|\\.)*)"', r2.text)
                    if mt:
                        try:
                            artist = json.loads('"' + mt.group(1) + '"')
                        except Exception:
                            artist = mt.group(1)
        except Exception:
            logger.warning("spotify meta failed")
        return (artist, title) if (title or artist) else None

    # ==== Yandex ====
    if "music.yandex" in url:
        try:
            from services.downloader import _yandex_meta
            meta = await _yandex_meta(url)
            if meta.title:
                return (meta.artist, meta.title)
        except Exception:
            logger.warning("yandex meta failed")
        return None

    # ==== Всё остальное — yt-dlp ====
    try:
        import yt_dlp
        loop = asyncio.get_event_loop()

        def _fetch():
            with yt_dlp.YoutubeDL(
                {"quiet": True, "skip_download": True, "no_warnings": True}
            ) as ydl:
                return ydl.extract_info(url, download=False)

        info = await loop.run_in_executor(None, _fetch)
        if info:
            title = info.get("title", "") or ""
            artist = info.get("artist") or info.get("uploader") or ""
            if artist.endswith(" - Topic"):
                artist = artist[:-8]
            if not info.get("artist") and " - " in title:
                parts = title.split(" - ", 1)
                artist = parts[0].strip()
                title = parts[1].strip()
            if title:
                return (artist, title)
    except Exception:
        logger.warning("ytdlp meta failed")
    return None