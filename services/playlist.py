"""Плейлисты: SoundCloud resolve + Deezer matching для Spotify/Yandex."""
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
# SoundCloud resolve
# ============================================================

async def _resolve_soundcloud_short(url: str) -> str:
    if "on.soundcloud.com" not in url:
        return url
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers={"User-Agent": UA}
        ) as c:
            r = await c.get(url)
            return str(r.url)
    except Exception:
        logger.exception("soundcloud resolve failed")
        return url


async def parse_soundcloud_playlist(url: str, max_tracks: int = 20):
    resolved = await _resolve_soundcloud_short(url)
    logger.info("soundcloud resolved: %s -> %s", url, resolved)
    return {"resolved_url": resolved, "type": "ytdlp", "max_tracks": max_tracks}


# ============================================================
# Deezer search
# ============================================================

async def _deezer_search_album(title: str, artist: str = ""):
    query = f"{title} {artist}".strip() if artist else title
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                "https://api.deezer.com/search/album",
                params={"q": query, "limit": 10},
            )
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:
        return None

    albums = data.get("data") or []
    if not albums:
        return None

    title_low = title.lower().strip()
    artist_low = artist.lower().strip()

    def score(a):
        s = 0
        at = (a.get("title") or "").lower().strip()
        ar = (a.get("artist", {}).get("name") or "").lower().strip()

        # Точное совпадение названия
        if at == title_low:
            s += 10
        elif title_low in at or at in title_low:
            s += 3

        # Совпадение артиста — критично
        if artist_low:
            if ar == artist_low:
                s += 15
            elif artist_low in ar or ar in artist_low:
                s += 8

        return s

    albums_with_score = [(a, score(a)) for a in albums]
    albums_with_score.sort(key=lambda x: x[1], reverse=True)
    best_album, best_score = albums_with_score[0]

    logger.info(
        "deezer search '%s' artist='%s' -> '%s' by '%s' (score=%d)",
        title, artist,
        best_album.get("title"), best_album.get("artist", {}).get("name"),
        best_score,
    )

    # Требуем минимальный score чтобы не хватать случайный
    if best_score < 3:
        return None

    return best_album.get("id")


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
    artist_main = (data.get("artist") or {}).get("name") or ""
    tracks_raw = data.get("tracks", {}).get("data") or []
    tracks = []
    for t in tracks_raw[:max_tracks]:
        name = t.get("title") or t.get("title_short") or ""
        artist = (t.get("artist") or {}).get("name") or artist_main
        duration = int(t.get("duration") or 0)
        if name:
            tracks.append(TrackRef(name=name, artist=artist, duration=duration))

    if not tracks:
        return None
    return PlaylistResult(title=title, tracks=tracks)


# ============================================================
# Spotify / Yandex via Deezer
# ============================================================

def _parse_og_title(title: str):
    """Возвращает (clean_title, artist_hint)."""
    title = title.strip()

    # Spotify: "Album Name - Album by Artist"
    m = re.search(r"\s*-\s*Album by\s+(.+)$", title, re.I)
    if m:
        artist = m.group(1).strip()
        clean = title[: m.start()].strip()
        # Убираем "Listen to " префикс
        clean = re.sub(r"^Listen to\s+", "", clean, flags=re.I)
        return clean, artist

    # Spotify: "Song Name - song and lyrics by Artist"
    m = re.search(r"\s*-\s*song (?:and lyrics )?by\s+(.+)$", title, re.I)
    if m:
        artist = m.group(1).strip()
        clean = title[: m.start()].strip()
        clean = re.sub(r"^Listen to\s+", "", clean, flags=re.I)
        return clean, artist

    # Yandex: "Album — Artist"
    for sep in [" — ", " – ", " - "]:
        if sep in title:
            parts = title.split(sep, 1)
            # У Яндекс обычно "Название — Артист"
            return parts[0].strip(), parts[1].strip()

    # Обычный: без артиста
    clean = re.sub(
        r"\s*[|—–]\s*(Spotify|Яндекс\.Музыка|Yandex Music|YouTube).*$",
        "", title, flags=re.I,
    )
    return clean.strip(), ""


async def parse_via_deezer(url: str, max_tracks: int = 20):
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

    clean_title, artist_hint = _parse_og_title(m.group(1))
    logger.info(
        "og:title parsed: title='%s' artist='%s'",
        clean_title, artist_hint,
    )

    if not clean_title:
        return None

    album_id = await _deezer_search_album(clean_title, artist_hint)
    if not album_id:
        # Пробуем без artist hint
        album_id = await _deezer_search_album(clean_title)
    if not album_id:
        # Убираем суффиксы
        stripped = re.sub(
            r"\s*\((?:Album|Deluxe|Remastered|Explicit|Single).*?\)",
            "", clean_title, flags=re.I,
        ).strip()
        if stripped and stripped != clean_title:
            album_id = await _deezer_search_album(stripped, artist_hint)

    if not album_id:
        return None
    return await _deezer_get_tracks(album_id, max_tracks=max_tracks)


async def parse_spotify_playlist(url: str, max_tracks: int = 20):
    return await parse_via_deezer(url, max_tracks=max_tracks)


async def parse_yandex_album(url: str, max_tracks: int = 20):
    return await parse_via_deezer(url, max_tracks=max_tracks)


async def parse_album_via_deezer(url: str, max_tracks: int = 20):
    return await parse_via_deezer(url, max_tracks=max_tracks)