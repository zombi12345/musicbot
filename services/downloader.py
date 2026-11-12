"""Скачивание: SoundCloud/YouTube напрямую, Spotify/Yandex через metadata + ytsearch5."""
import asyncio
import json
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

def _resolve_ffmpeg() -> str | None:
    env_path = os.getenv("FFMPEG_LOCATION", "").strip()
    if env_path and os.path.exists(env_path):
        return env_path
    # 1) PATH (Windows: ffmpeg.exe, Linux: ffmpeg)
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    # 2) imageio-ffmpeg (bundled binary)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return None

def _setup_cookies_from_env():
    """Декодирует YT_COOKIES_BASE64 из env в /tmp/cookies.txt."""
    import base64
    b64 = os.getenv("YT_COOKIES_BASE64", "").strip()
    if not b64:
        return None
    try:
        data = base64.b64decode(b64)
        path = "/tmp/yt_cookies.txt" if os.name == "posix" else str(Path(__import__("tempfile").gettempdir()) / "yt_cookies.txt")
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception:
        return None


COOKIES_FILE = os.getenv("YT_COOKIES_FILE", "").strip() or _setup_cookies_from_env()

FFMPEG_LOCATION = _resolve_ffmpeg()
SPOTIFY_OEMBED = "https://open.spotify.com/oembed"
SPOTIFY_EMBED = "https://open.spotify.com/embed/track/{id}"
ITUNES_SEARCH = "https://itunes.apple.com/search"
DEEZER_SEARCH = "https://api.deezer.com/search"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MIN_MATCH_SCORE = 4


@dataclass
class TrackMeta:
    artist: str = ""
    title: str = ""
    duration: int = 0
    source: str = "unknown"


@dataclass
class DownloadResult:
    filepath: Path
    title: str
    performer: str
    duration: int = 0
    platform: str = "unknown"


# ============================================================
# Parsers
# ============================================================

def _parse_next_data(html_text):
    """Spotify __NEXT_DATA__ - самый надёжный источник artist/title/duration."""
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL)
    if not m:
        return TrackMeta()
    try:
        data = json.loads(m.group(1))
    except Exception:
        return TrackMeta()
    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError):
        return TrackMeta()
    meta = TrackMeta(source="spotify_next")
    meta.title = (entity.get("name") or "").strip()
    artists = entity.get("artists") or []
    if isinstance(artists, list):
        meta.artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name"))
    elif isinstance(entity.get("subtitle"), str):
        meta.artist = entity["subtitle"].strip()
    dur = entity.get("duration") or 0
    if dur:
        meta.duration = int(dur) // 1000
    return meta


def _parse_json_ld(html_text):
    meta = TrackMeta()
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html_text, re.DOTALL):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            typ = it.get("@type", "")
            if isinstance(typ, str):
                typ = [typ]
            if not any(t in ("MusicRecording", "Song", "MusicComposition", "MusicAlbum") for t in (typ or [])):
                continue
            if not meta.title:
                meta.title = (it.get("name") or "").strip()
            by = it.get("byArtist") or it.get("composer") or it.get("author")
            if not meta.artist:
                if isinstance(by, dict):
                    meta.artist = (by.get("name") or "").strip()
                elif isinstance(by, list):
                    meta.artist = ", ".join((b.get("name", "") if isinstance(b, dict) else str(b)) for b in by if b)
            dur = it.get("duration", "")
            if dur and dur.startswith("PT") and not meta.duration:
                m2 = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
                if m2:
                    h, mi, s = (int(x) if x else 0 for x in m2.groups())
                    meta.duration = h * 3600 + mi * 60 + s
            if meta.title and meta.artist:
                return meta
    return meta


def _parse_og(html_text):
    meta = TrackMeta()
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if m:
        meta.title = m.group(1).strip()
    m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if m:
        desc = m.group(1).strip()
        for sep in [" · ", " — ", " – ", " - "]:
            if sep in desc:
                head = desc.split(sep, 1)[0].strip()
                if head and len(head) < 100 and not head.lower().startswith("listen to"):
                    meta.artist = head
                break
    if meta.title:
        meta.title = re.sub(r'\s*[|—–]\s*(Spotify|Яндекс\.Музыка|Yandex Music|YouTube).*$', '', meta.title, flags=re.I)
        meta.title = re.sub(r'\s*[-–—]\s*song (and lyrics )?by.*$', '', meta.title, flags=re.I)
    return meta


async def _fetch_html(url):
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ru;q=0.8"}, follow_redirects=True) as c:
            r = await c.get(url)
            if r.status_code != 200:
                return ""
            return r.text
    except Exception as e:
        logger.warning("fetch %s failed: %s", url, e)
        return ""


# ============================================================
# External APIs
# ============================================================

async def _deezer_meta(query):
    """Deezer API - бесплатный, отлично знает русскую музыку."""
    if not query:
        return TrackMeta(source="deezer")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(DEEZER_SEARCH, params={"q": query, "limit": 5})
            if r.status_code != 200:
                return TrackMeta(source="deezer")
            data = r.json()
    except Exception as e:
        logger.warning("Deezer failed: %s", e)
        return TrackMeta(source="deezer")

    items = data.get("data") or []
    if not items:
        return TrackMeta(source="deezer")

    q_low = query.lower()

    def _s(item):
        s = 0
        t = (item.get("title") or "").lower()
        a = ((item.get("artist") or {}).get("name") or "").lower()
        if t and t in q_low:
            s += 3
        if a and a in q_low:
            s += 3
        return s

    items.sort(key=_s, reverse=True)
    first = items[0]
    return TrackMeta(
        artist=((first.get("artist") or {}).get("name") or "").strip(),
        title=(first.get("title") or "").strip(),
        duration=int(first.get("duration") or 0),
        source="deezer",
    )


async def _itunes_meta(query):
    if not query:
        return TrackMeta(source="itunes")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(ITUNES_SEARCH, params={"term": query, "media": "music", "limit": 5})
            if r.status_code != 200:
                return TrackMeta(source="itunes")
            data = r.json()
    except Exception:
        return TrackMeta(source="itunes")
    results = data.get("results") or []
    if not results:
        return TrackMeta(source="itunes")
    q_low = query.lower()

    def _s(r):
        s = 0
        t = (r.get("trackName") or "").lower()
        a = (r.get("artistName") or "").lower()
        if t and t in q_low:
            s += 3
        if a and a in q_low:
            s += 3
        return s

    results.sort(key=_s, reverse=True)
    first = results[0]
    return TrackMeta(
        artist=(first.get("artistName") or "").strip(),
        title=(first.get("trackName") or "").strip(),
        duration=int((first.get("trackTimeMillis") or 0) // 1000),
        source="itunes",
    )


# ============================================================
# Platform metadata
# ============================================================

async def _spotify_meta(url):
    meta = TrackMeta(source="spotify")

    # 1) HTML страницы -> __NEXT_DATA__
    html_text = await _fetch_html(url)
    if html_text:
        nd = _parse_next_data(html_text)
        if nd.title:
            meta.title = nd.title
        if nd.artist:
            meta.artist = nd.artist
        if nd.duration:
            meta.duration = nd.duration
        if meta.title and meta.artist:
            logger.info("Spotify NEXT_DATA OK: artist=%r title=%r dur=%d", meta.artist, meta.title, meta.duration)
            return meta

        # JSON-LD
        if not (meta.title and meta.artist):
            ld = _parse_json_ld(html_text)
            if ld.title and not meta.title:
                meta.title = ld.title
            if ld.artist and not meta.artist:
                meta.artist = ld.artist
            if ld.duration and not meta.duration:
                meta.duration = ld.duration

        # og fallback
        og = _parse_og(html_text)
        if og.title and not meta.title:
            meta.title = og.title
        if og.artist and not meta.artist:
            meta.artist = og.artist

    # 2) oEmbed title
    if not meta.title:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(SPOTIFY_OEMBED, params={"url": url})
                if r.status_code == 200:
                    meta.title = (r.json().get("title") or "").strip()
        except Exception as e:
            logger.warning("oEmbed failed: %s", e)

    # 3) Embed endpoint
    if not meta.artist:
        m = re.search(r"/track/([a-zA-Z0-9]+)", url)
        if m:
            try:
                async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
                    r = await c.get(SPOTIFY_EMBED.format(id=m.group(1)))
                    if r.status_code == 200:
                        t = r.text
                        mt = re.search(r'"subtitle"\s*:\s*"((?:[^"\\]|\\.)*)"', t)
                        if mt and not meta.artist:
                            try:
                                meta.artist = json.loads('"' + mt.group(1) + '"')
                            except Exception:
                                meta.artist = mt.group(1)
            except Exception:
                pass

    # 4) Deezer
    if meta.title and not meta.artist:
        dz = await _deezer_meta(meta.title)
        if dz.artist:
            logger.info("Deezer enriched: artist=%r title=%r dur=%d", dz.artist, dz.title, dz.duration)
            meta.artist = dz.artist
            if dz.duration and not meta.duration:
                meta.duration = dz.duration

    # 5) iTunes
    if meta.title and not meta.artist:
        it = await _itunes_meta(meta.title)
        if it.artist:
            logger.info("iTunes enriched: artist=%r", it.artist)
            meta.artist = it.artist
            if it.duration and not meta.duration:
                meta.duration = it.duration

    logger.info("Spotify final: artist=%r title=%r dur=%d", meta.artist, meta.title, meta.duration)
    return meta


async def _yandex_meta(url):
    html_text = await _fetch_html(url)
    if not html_text:
        return TrackMeta(source="yandex")
    ld = _parse_json_ld(html_text)
    if not (ld.title and ld.artist):
        og = _parse_og(html_text)
        if not ld.title:
            ld.title = og.title
        if not ld.artist:
            ld.artist = og.artist
    ld.source = "yandex"
    return ld


# ============================================================
# yt-dlp
# ============================================================

def _ydl_opts(fmt, fast: bool = False):
    """fast=True — для плейлистов: быстрее падать, меньше retries."""
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "color": "no_color",
        "retries": 2 if fast else 4,
        "fragment_retries": 2 if fast else 4,
        "socket_timeout": 15 if fast else 25,
        "file_access_retries": 2,
        "extractor_retries": 2 if fast else 3,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        },
        "geo_bypass": True,
        # Пробуем разные клиенты YouTube — уменьшает ConnectionResetError
        "extractor_args": {
            "youtube": {"player_client": ["tv", "mweb"]},
        },
    }
    if FFMPEG_LOCATION:
        opts["ffmpeg_location"] = FFMPEG_LOCATION
    opts["postprocessors"] = [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "320" if fmt == "mp3_320" else "192",
    }]
    return opts


def _score(entry, meta):
    s = 0
    t = (entry.get("title") or "").lower()
    u = (entry.get("uploader") or "").lower()
    d = entry.get("duration") or 0
    title_l = (meta.title or "").lower()
    artist_l = (meta.artist or "").lower()

    if title_l:
        if title_l == t:
            s += 5
        elif title_l in t:
            s += 3

    if artist_l:
        if artist_l in t:
            s += 2
        if artist_l in u:
            s += 2

    if "official" in t:
        s += 1
    if "audio" in t:
        s += 1
    if meta.duration and d:
        diff = abs(d - meta.duration)
        if diff <= 5:
            s += 10       # почти точное совпадение — огромный бонус
        elif diff <= 15:
            s += 4
        elif diff > 60:
            s -= 5        # слишком далеко — штраф
    return s


def _sync_search_dl(query, meta, fmt, strict, fast: bool = False):
    """Сначала SoundCloud, потом YouTube (обход блокировки Render IP)."""
    # Извлекаем "искомое" из query (ytsearch5:ARTIST TITLE)
    raw_query = query
    for prefix in ("ytsearch5:", "scsearch5:", "scsearch3:", "ytsearch3:", "ytsearch1:"):
        if raw_query.startswith(prefix):
            raw_query = raw_query[len(prefix):]
            break

    # ==== Попытка 1: SoundCloud ====
    try:
        sc_query = f"scsearch5:{raw_query}"
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "no_color": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(sc_query, download=False)
        if info and "entries" in info:
            entries = [e for e in info["entries"] if e and (e.get("duration") or 0) >= 60]
            if entries:
                scored = [(e, _score(e, meta)) for e in entries]
                scored.sort(key=lambda x: x[1], reverse=True)
                best, best_score = scored[0]
                logger.info("SC top: %s (score=%d)", [(e.get("title","?")[:40], s) for e, s in scored[:3]], best_score)
                if best_score >= 3:
                    best_url = best.get("webpage_url") or best.get("url")
                    logger.info("SC picked: %s | score=%d", best.get("title"), best_score)
                    opts = _ydl_opts(fmt, fast=fast)
                    opts["outtmpl"] = str(DOWNLOAD_DIR / "%(title).80s.%(ext)s")
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        dl = ydl.extract_info(best_url, download=True)
                        if "entries" in dl:
                            dl = dl["entries"][0]
                        fp = Path(ydl.prepare_filename(dl)).with_suffix(".mp3")
                    final_title = meta.title or dl.get("title") or "Unknown"
                    final_artist = meta.artist or dl.get("uploader") or "Unknown"
                    try:
                        a = MP3(str(fp))
                        if a.tags is None:
                            a.add_tags()
                        a.tags.add(TIT2(encoding=3, text=final_title))
                        a.tags.add(TPE1(encoding=3, text=final_artist))
                        a.save()
                    except Exception:
                        pass
                    return DownloadResult(filepath=fp, title=final_title, performer=final_artist, duration=int(dl.get("duration") or 0))
    except Exception as e:
        logger.info("SC failed, trying YouTube: %s", str(e)[:100])

    # ==== Попытка 2: YouTube ====
    yt_query = f"ytsearch5:{raw_query}"
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "no_color": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(yt_query, download=False)
    if not info or "entries" not in info:
        raise RuntimeError("Поиск не дал результатов")
    entries = [e for e in info["entries"] if e]
    if not entries:
        raise RuntimeError("Поиск пустой")
    scored = [(e, _score(e, meta)) for e in entries]
    scored.sort(key=lambda x: x[1], reverse=True)
    best, best_score = scored[0]
    logger.info("YT top: %s (score=%d)", [(e.get("title","?")[:40], s) for e, s in scored[:3]], best_score)
    if strict and best_score < MIN_MATCH_SCORE:
        raise RuntimeError(f"Нет точного совпадения (score {best_score})")
    best_url = best.get("webpage_url") or best.get("url")
    logger.info("YT picked: %s | score=%d", best.get("title"), best_score)
    opts = _ydl_opts(fmt, fast=fast)
    opts["outtmpl"] = str(DOWNLOAD_DIR / "%(title).80s.%(ext)s")
    with yt_dlp.YoutubeDL(opts) as ydl:
        dl = ydl.extract_info(best_url, download=True)
        if "entries" in dl:
            dl = dl["entries"][0]
        fp = Path(ydl.prepare_filename(dl)).with_suffix(".mp3")
    final_title = meta.title or dl.get("title") or "Unknown"
    final_artist = meta.artist or dl.get("uploader") or "Unknown"
    try:
        a = MP3(str(fp))
        if a.tags is None:
            a.add_tags()
        a.tags.add(TIT2(encoding=3, text=final_title))
        a.tags.add(TPE1(encoding=3, text=final_artist))
        a.save()
    except Exception:
        pass
    return DownloadResult(filepath=fp, title=final_title, performer=final_artist, duration=int(dl.get("duration") or 0))


def _sync_direct(url, fmt, fast: bool = False):
    opts = _ydl_opts(fmt, fast=fast)
    opts["outtmpl"] = str(DOWNLOAD_DIR / "%(title).80s.%(ext)s")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if "entries" in info:
            info = info["entries"][0]
        fp = Path(ydl.prepare_filename(info)).with_suffix(".mp3")
    title = info.get("title") or "Unknown"
    performer = info.get("uploader") or info.get("artist") or "Unknown"
    dur = int(info.get("duration") or 0)
    try:
        a = MP3(str(fp))
        if a.tags is None:
            a.add_tags()
        a.tags.add(TIT2(encoding=3, text=title))
        a.tags.add(TPE1(encoding=3, text=performer))
        a.save()
    except Exception as e:
        logger.warning("Tags failed: %s", e)
    return DownloadResult(filepath=fp, title=title, performer=performer, duration=dur)


async def download_audio(url, audio_format="mp3_320"):
    platform = detect_platform(url)
    if platform == Platform.SPOTIFY:
        meta = await _spotify_meta(url)
        if not meta.title:
            raise RuntimeError("Не удалось извлечь метаданные Spotify")
        q = f"ytsearch5:{meta.artist} {meta.title}" if meta.artist else f"ytsearch5:{meta.title} audio"
        logger.info("Spotify query: %s", q)
        r = await asyncio.to_thread(_sync_search_dl, q, meta, audio_format, True)
        r.platform = "spotify"
        return r
    if platform == Platform.YANDEX:
        meta = await _yandex_meta(url)
        if not meta.title:
            raise RuntimeError("Не удалось извлечь метаданные Яндекс.Музыки. Пришли ссылку на SoundCloud или YouTube.")
        q = f"ytsearch5:{meta.artist} {meta.title}" if meta.artist else f"ytsearch5:{meta.title} audio"
        logger.info("Yandex query: %s", q)
        r = await asyncio.to_thread(_sync_search_dl, q, meta, audio_format, True)
        r.platform = "yandex"
        return r
    if platform in (Platform.SOUNDCLOUD, Platform.YOUTUBE):
        try:
            r = await asyncio.to_thread(_sync_direct, url, audio_format, fast=True)
        except Exception as _e:
            _es = str(_e).lower()
            if any(x in _es for x in ("sign in", "failed to extract", "player response", "not a bot")):
                raise RuntimeError(
                    "⚠ YouTube блокирует наш сервер, поэтому эту ссылку скачать не могу.\n\n"
                    "💡 Что делать:\n"
                    "• Пришли этот же трек со SoundCloud — качаем без проблем\n"
                    "• Spotify-ссылки работают (через SoundCloud)\n"
                    "• YouTube-ссылки временно недоступны с этого сервера"
                )
            raise
        r.platform = platform.value
        return r
    raise RuntimeError(f"Платформа не поддерживается: {platform.value}")


def cleanup(path):
    try:
        if path and Path(path).exists():
            Path(path).unlink()
    except Exception as e:
        logger.warning("cleanup failed: %s", e)