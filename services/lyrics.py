"""Поиск текста песен: lrclib.net (primary) + lyrics.ovh (fallback)."""
import logging
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

LRCLIB_URL = "https://lrclib.net/api/get"
LYRICS_OVH_URL = "https://api.lyrics.ovh/v1/{artist}/{title}"
UA = "MusicBot/1.0 (https://t.me/)"


async def _try_lrclib(artist: str, title: str):
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
            r = await c.get(
                LRCLIB_URL,
                params={"artist_name": artist, "track_name": title},
            )
            if r.status_code == 200:
                data = r.json()
                text = data.get("plainLyrics") or data.get("syncedLyrics")
                if text:
                    return text
    except Exception:
        logger.exception("lrclib failed")
    return None


async def _try_lyrics_ovh(artist: str, title: str):
    try:
        a = urllib.parse.quote(artist)
        t = urllib.parse.quote(title)
        url = LYRICS_OVH_URL.format(artist=a, title=t)
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url)
            if r.status_code == 200:
                data = r.json()
                text = data.get("lyrics")
                if text:
                    return text
    except Exception:
        logger.exception("lyrics.ovh failed")
    return None


async def fetch_lyrics(artist: str, title: str):
    """Возвращает dict {source, lyrics} или None."""
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not title:
        return None
    if not artist:
        # lrclib требует artist — попробуем без
        pass

    text = await _try_lrclib(artist, title)
    if text:
        return {"source": "lrclib", "lyrics": text}

    text = await _try_lyrics_ovh(artist, title)
    if text:
        return {"source": "lyrics.ovh", "lyrics": text}

    return None


def clean_lyrics(text: str) -> str:
    """Убирает артефакты типа \\r\\n, лишние пустые строки."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    # Сжимаем 3+ пустых строки в 1
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()