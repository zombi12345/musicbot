import json
import logging
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


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


async def parse_spotify_playlist(url: str, max_tracks: int = 20) -> PlaylistResult | None:
    try:
        async with httpx.AsyncClient(
            timeout=25,
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ru;q=0.8"},
            follow_redirects=True,
        ) as c:
            r = await c.get(url)
            if r.status_code != 200:
                return None
            html = r.text
    except Exception:
        logger.exception("playlist fetch failed")
        return None

    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except Exception:
        return None

    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError):
        return None

    title = entity.get("name") or entity.get("title") or "Playlist"
    tracks_raw = entity.get("trackList") or entity.get("tracks") or []
    if isinstance(tracks_raw, dict):
        tracks_raw = tracks_raw.get("items", [])

    result = PlaylistResult(title=title)
    for t in tracks_raw:
        if len(result.tracks) >= max_tracks:
            break
        if not isinstance(t, dict):
            continue
        name = t.get("title") or t.get("name") or ""
        artist = t.get("subtitle") or ""
        uri = t.get("uri", "")
        track_url = ""
        if isinstance(uri, str) and uri.startswith("spotify:track:"):
            track_url = "https://open.spotify.com/track/" + uri.split(":")[-1]
        if not name and isinstance(t.get("track"), dict):
            inner = t["track"]
            name = inner.get("name", "")
            artists = inner.get("artists") or []
            if isinstance(artists, list):
                artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict))
            iuri = inner.get("uri", "")
            if iuri.startswith("spotify:track:"):
                track_url = "https://open.spotify.com/track/" + iuri.split(":")[-1]
        if name:
            result.tracks.append(TrackRef(
                name=name, artist=artist,
                duration=int(t.get("duration") or 0),
                url=track_url,
            ))
    return result

async def parse_yandex_album(url: str, max_tracks: int = 20):
    """Парсит альбом/плейлист Яндекс.Музыки через HTML JSON-LD."""
    import json as _json
    import re as _re

    try:
        async with httpx.AsyncClient(
            timeout=25,
            headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
            follow_redirects=True,
        ) as c:
            r = await c.get(url)
            if r.status_code != 200:
                logger.warning("yandex %s -> %s", url, r.status_code)
                return None
            html = r.text
    except Exception:
        logger.exception("yandex fetch failed")
        return None

    title = "Альбом Яндекс.Музыки"
    tracks = []

    # Ищем все JSON-LD
    for m in _re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, _re.DOTALL,
    ):
        try:
            data = _json.loads(m.group(1).strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            typ = it.get("@type", "")
            if typ in ("MusicAlbum", "MusicPlaylist"):
                title = it.get("name") or title
                tracks_raw = it.get("track") or []
                if isinstance(tracks_raw, dict):
                    tracks_raw = [tracks_raw]
                for t in tracks_raw:
                    if not isinstance(t, dict):
                        continue
                    name = t.get("name") or ""
                    artist = ""
                    by = t.get("byArtist")
                    if isinstance(by, dict):
                        artist = by.get("name", "")
                    elif isinstance(by, list) and by:
                        artist = by[0].get("name", "") if isinstance(by[0], dict) else ""
                    # duration из ISO
                    dur = t.get("duration", "")
                    duration = 0
                    if isinstance(dur, str) and dur.startswith("PT"):
                        mm = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
                        if mm:
                            h, mi, s = (int(x) if x else 0 for x in mm.groups())
                            duration = h * 3600 + mi * 60 + s
                    if name:
                        tracks.append({
                            "name": name,
                            "artist": artist,
                            "duration": duration,
                            "url": "",
                        })

    # Fallback: og:title
    if not tracks:
        m = _re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html,
        )
        if m:
            title = m.group(1).strip()

    if not tracks:
        return None

    # Возвращаем в формате PlaylistResult
    return PlaylistResult(
        title=title,
        tracks=[
            TrackRef(
                name=t["name"],
                artist=t["artist"],
                duration=t["duration"],
                url=t["url"],
            )
            for t in tracks[:max_tracks]
        ],
    )