"""Плейлисты: SoundCloud (yt-dlp) + Spotify/Yandex (Deezer bridge)."""
import logging
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)
UA = "MusicBot/1.0"


@dataclass
class TrackRef:
    name: str
    artist: str
    duration: int = 0
    url: str = ""


@dataclass
class PlaylistResult:
    title: str
    tracks: list = field(default_factory=list)


# ============================================================
# SOUNDCLOUD: разворот короткой ссылки
# ============================================================

async def _resolve_soundcloud_short(url: str) -> str:
    if "on.soundcloud.com" not in url:
        return url
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers={"User-Agent": UA}
        ) as c:
            r = await c.get(url)
            final = str(r.url)
            logger.info("soundcloud short -> %s", final)
            return final
    except Exception:
        logger.exception("soundcloud resolve failed")
        return url


async def parse_soundcloud_playlist(url: str, max_tracks: int = 20):
    resolved = await _resolve_soundcloud_short(url)
    return {"resolved_url": resolved, "type": "ytdlp", "max_tracks": max_tracks}


# ============================================================
# DEEZER: fallback для Spotify / Yandex
# ============================================================

async def _deezer_search_album(query: str, artist_hint: str = ""):
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                "https://api.deezer.com/search/album",
                params={"q": query, "limit": 5},
            )
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:
        return None

    albums = data.get("data") or []
    if not albums:
        return None

    q_low = query.lower()
    artist_low = (artist_hint or "").lower()

    def score(a):
        s = 0
        t = (a.get("title") or "").lower()
        ar = (a.get("artist", {}).get("name") or "").lower()
        if t == q_low:
            s += 5
        elif q_low in t or t in q_low:
            s += 3
        if artist_low and artist_low in ar:
            s += 4
        return s

    albums.sort(key=score, reverse=True)
    return albums[0].get("id")


async def _deezer_get_tracks(album_id: int, max_tracks: int = 20):
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"https://api.deezer.com/album/{album_id}")
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:
        return None

    title = data.get("title") or "Album"
    tracks_raw = data.get("tracks", {}).get("data") or []
    tracks = []
    for t in tracks_raw[:max_tracks]:
        name = t.get("title") or t.get("title_short") or ""
        artist = (t.get("artist") or {}).get("name") or ""
        duration = int(t.get("duration") or 0)
        if name:
            tracks.append(TrackRef(name=name, artist=artist, duration=duration))

    if not tracks:
        return None
    return PlaylistResult(title=title, tracks=tracks)


async def parse_via_deezer(url: str, max_tracks: int = 20):
    """og:title + Deezer поиск (Spotify, Yandex)."""
    try:
        async with httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
            follow_redirects=True,
        ) as c:
            r = await c.get(url)
            if r.status_code != 200:
                return None
            html = r.text
    except Exception:
        return None

    m = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        html,
    )
    if not m:
        return None

    title = m.group(1).strip()
    title = re.sub(
        r"\s*[|—–]\s*(Spotify|Яндекс\.Музыка|Yandex Music|YouTube).*$",
        "", title, flags=re.I,
    )
    title = re.sub(r"\s*[-–—]\s*song (and lyrics )?by.*$", "", title, flags=re.I)

    album_id = await _deezer_search_album(title)
    if not album_id:
        clean = re.sub(r"\s*\((?:Album|Deluxe|Remastered|Explicit).*?\)", "", title, flags=re.I)
        clean = clean.split(" - ")[0].strip()
        if clean and clean != title:
            album_id = await _deezer_search_album(clean)
    if not album_id:
        # Пробуем только первое слово / имя артиста
        parts = title.split()
        if parts:
            album_id = await _deezer_search_album(parts[0])

    if not album_id:
        return None
    return await _deezer_get_tracks(album_id, max_tracks=max_tracks)


async def parse_spotify_playlist(url: str, max_tracks: int = 20):
    return await parse_via_deezer(url, max_tracks=max_tracks)


async def parse_yandex_album(url: str, max_tracks: int = 20):
    return await parse_via_deezer(url, max_tracks=max_tracks)


async def parse_album_via_deezer(url: str, max_tracks: int = 20):
    return await parse_via_deezer(url, max_tracks=max_tracks)