"""Lyrics: lrclib (get+search) + lyrics.ovh + alternative queries."""
import asyncio
import logging
import re
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

LRCLIB_GET = "https://lrclib.net/api/get"
LRCLIB_SEARCH = "https://lrclib.net/api/search"
LYRICS_OVH = "https://api.lyrics.ovh/v1/{artist}/{title}"
UA = "MusicBot/1.0"

_TIMESTAMP_RE = re.compile(r"\[\d{1,3}:\d{2}(?:[\.:]\d{1,3})?\]\s*")


def _clean_timestamps(text: str) -> str:
    if not text:
        return ""
    return _TIMESTAMP_RE.sub("", text)


def clean_lyrics(text: str) -> str:
    if not text:
        return ""
    text = _clean_timestamps(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.strip() for line in text.split("\n"))
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def _pick_best_lyrics(data: dict):
    """Из результата lrclib берём plainLyrics или очищенный syncedLyrics."""
    plain = data.get("plainLyrics")
    if plain and plain.strip():
        return plain
    synced = data.get("syncedLyrics")
    if synced and synced.strip():
        cleaned = _clean_timestamps(synced)
        if cleaned.strip():
            return cleaned
    return None


async def _lrclib_get(artist: str, title: str):
    """Точный матч."""
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}) as c:
            r = await c.get(LRCLIB_GET, params={"artist_name": artist, "track_name": title})
            if r.status_code == 200:
                return _pick_best_lyrics(r.json())
    except Exception:
        logger.warning("lrclib get failed")
    return None


async def _lrclib_search(query: str):
    """Поиск по строке — работает даже когда точного матча нет."""
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}) as c:
            r = await c.get(LRCLIB_SEARCH, params={"q": query})
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:
        logger.warning("lrclib search failed")
        return None

    if not isinstance(data, list) or not data:
        return None

    # Берём первый результат с lyrics
    for item in data:
        lyrics = _pick_best_lyrics(item)
        if lyrics:
            return lyrics
    return None


async def _lyrics_ovh(artist: str, title: str):
    if not artist or not title:
        return None
    try:
        a = urllib.parse.quote(artist)
        t = urllib.parse.quote(title)
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(LYRICS_OVH.format(artist=a, title=t))
            if r.status_code == 200:
                return r.json().get("lyrics")
    except Exception:
        logger.warning("lyrics.ovh failed")
    return None


def _translit_ru_to_en(text: str) -> str:
    """Баста → Basta (простая транслитерация)."""
    mapping = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    result = []
    for ch in text.lower():
        result.append(mapping.get(ch, ch))
    return "".join(result).title()


async def fetch_lyrics(artist: str, title: str):
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not title:
        return None

    # ==== Попытка 1: точный lrclib.get ====
    if artist:
        text = await _lrclib_get(artist, title)
        if text:
            return {"source": "lrclib", "lyrics": text}

    # ==== Попытка 2: lrclib.search (artist + title) ====
    query = f"{artist} {title}".strip() if artist else title
    text = await _lrclib_search(query)
    if text:
        return {"source": "lrclib-search", "lyrics": text}

    # ==== Попытка 3: lrclib.search только title ====
    if artist:
        text = await _lrclib_search(title)
        if text:
            return {"source": "lrclib-title", "lyrics": text}

    # ==== Попытка 4: lyrics.ovh (оригинал) ====
    text = await _lyrics_ovh(artist, title)
    if text:
        return {"source": "lyrics.ovh", "lyrics": text}

    # ==== Попытка 5: транслитерация (Баста → Basta) ====
    if artist and re.search(r"[а-яА-Я]", artist):
        artist_en = _translit_ru_to_en(artist)
        title_en = _translit_ru_to_en(title)
        text = await _lrclib_get(artist_en, title_en)
        if text:
            return {"source": "lrclib-en", "lyrics": text}
        text = await _lrclib_search(f"{artist_en} {title_en}")
        if text:
            return {"source": "lrclib-search-en", "lyrics": text}

    return None


async def extract_meta_from_url(url: str):
    """(artist, title) из URL: Spotify / Yandex / yt-dlp."""
    import json

    if "spotify.com" in url:
        m = re.search(r"/track/([a-zA-Z0-9]+)", url)
        if not m:
            return None
        sid = m.group(1)
        title = artist = ""
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
            pass
        return (artist, title) if (title or artist) else None

    if "music.yandex" in url:
        try:
            from services.downloader import _yandex_meta
            meta = await _yandex_meta(url)
            if meta.title:
                return (meta.artist, meta.title)
        except Exception:
            pass
        return None

    try:
        import yt_dlp
        loop = asyncio.get_event_loop()

        def _fetch():
            with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True, "no_color": True}) as ydl:
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
        pass
    return None