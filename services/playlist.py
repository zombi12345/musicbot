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