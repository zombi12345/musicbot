"""Скачивание аудио через yt-dlp + метаданные через mutagen.

Платформы:
  - SoundCloud, YouTube  -> прямой yt-dlp
  - Spotify              -> JSON-LD/oEmbed -> ytsearch5 + scoring
  - Яндекс.Музыка        -> JSON-LD/og со страницы -> ytsearch5 + scoring
"""
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

FFMPEG_LOCATION = os.getenv("FFMPEG_LOCATION", "").strip() or None
SPOTIFY_OEMBED = "https://open.spotify.com/oembed"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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
# Metadata parsing
# ============================================================

def _parse_json_ld(html: str) -> TrackMeta:
    meta = TrackMeta()
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    ):
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
            if not any(t in ("MusicRecording", "Song", "MusicComposition", "MusicAlbum") for t in typ or []):
                continue
            if not meta.title:
                meta.title = (it.get("name") or "").strip()
            by = it.get("byArtist") or it.get("composer") or it.get("author")
            if not meta.artist:
                if isinstance(by, dict):
                    meta.artist = (by.get("name") or "").strip()
                elif isinstance(by, list):
                    names = [
                        b.get("name", "") if isinstance(b, dict) else str(b)
                        for b in by if b
                    ]
                    meta.artist = ", ".join(n for n in names if n)
            dur = it.get("duration", "")
            if dur and dur.startswith("PT") and not meta.duration:
                m2 = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
                if m2:
                    h, mi, s = (int(x) if x else 0 for x in m2.groups())
                    meta.duration = h * 3600 + mi * 60 + s
            if meta.title and meta.artist:
                return meta
    return meta


def _parse_og(html: str) -> TrackMeta:
    meta = TrackMeta()
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html)
    if m:
        meta.title = m.group(1).strip()
    m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html)
    if m:
        desc = m.group(1).strip()
        # "Artist · Song" / "Artist — Song" / "Artist - Song"
        for sep in [" · ", " — ", " – ", " - "]:
            if sep in desc:
                head = desc.split(sep, 1)[0].strip()
                if head and len(head) < 100:
                    meta.artist = head
                break
    # clean title
    if meta.title:
        meta.title = re.sub(
            r'\s*[|—–]\s*(Spotify|Яндекс\.Музыка|Yandex Music|YouTube).*$',
            '', meta.title, flags=re.I,
        )
        meta.title = re.sub(r'\s*[-–—]\s*song (and lyrics )?by.*$', '', meta.title, flags=re.I)
        meta.title = re.sub(r'\s*[-–—]\s*слушать.*$', '', meta.title, flags=re.I)
    return meta


async def _fetch_page_meta(url: str) -> TrackMeta:
    try:
        async with httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ru;q=0.8"},
            follow_redirects=True,
        ) as c:
            r = await c.get(url)
            if r.status_code != 200:
                logger.warning("Page %s -> %s", url, r.status_code)
                return TrackMeta()
            html = r.text
    except Exception as e:
        logger.warning("Page fetch failed: %s", e)
        return TrackMeta()

    ld = _parse_json_ld(html)
    if ld.title and ld.artist:
        return ld

    og = _parse_og(html)
    if not ld.title:
        ld.title = og.title
    if not ld.artist:
        ld.artist = og.artist
    return ld


async def _spotify_meta(url: str) -> TrackMeta:
    meta = TrackMeta(source="spotify")
    # 1) oEmbed (title)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(SPOTIFY_OEMBED, params={"url": url})
            if r.status_code == 200:
                meta.title = (r.json().get("title") or "").strip()
    except Exception as e:
        logger.warning("Spotify oEmbed failed: %s", e)
    # 2) page (JSON-LD / og)
    page = await _fetch_page_meta(url)
    if page.title:
        meta.title = page.title
    if page.artist:
        meta.artist = page.artist
    if page.duration:
        meta.duration = page.duration
    return meta


async def _yandex_meta(url: str) -> TrackMeta:
    page = await _fetch_page_meta(url)
    page.source = "yandex"
    return page


# ============================================================
# yt-dlp
# ============================================================

def _ydl_opts(audio_format: str) -> dict:
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if FFMPEG_LOCATION:
        opts["ffmpeg_location"] = FFMPEG_LOCATION
    opts["postprocessors"] = [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "320" if audio_format == "mp3_320" else "192",
    }]
    return opts


def _score_result(entry: dict, meta: TrackMeta) -> int:
    score = 0
    t = (entry.get("title") or "").lower()
    u = (entry.get("uploader") or "").lower()
    d = entry.get("duration") or 0
    if meta.title and meta.title.lower() in t:
        score += 3
    if meta.artist and meta.artist.lower() in t:
        score += 2
    if meta.artist and meta.artist.lower() in u:
        score += 2
    if "official" in t:
        score += 1
    if "audio" in t:
        score += 1
    if "lyric" in t:
        score += 1
    if meta.duration and d and abs(d - meta.duration) <= 5:
        score += 4
    return score


def _sync_search_and_download(query_url: str, meta: TrackMeta, audio_format: str) -> DownloadResult:
    # 1) search top-5
    search_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(search_opts) as ydl:
        info = ydl.extract_info(query_url, download=False)
    if not info or "entries" not in info:
        raise RuntimeError("Поиск не дал результатов")
    entries = [e for e in info["entries"] if e]
    if not entries:
        raise RuntimeError("Поиск пустой")

    best = max(entries, key=lambda e: _score_result(e, meta))
    best_url = best.get("webpage_url") or best.get("url")
    if not best_url:
        raise RuntimeError("Не нашёл URL у результата")

    logger.info(
        "Picked: %s | score=%d | yt_dur=%s meta_dur=%s",
        best.get("title"), _score_result(best, meta),
        best.get("duration"), meta.duration,
    )

    # 2) download
    opts = _ydl_opts(audio_format)
    opts["outtmpl"] = str(DOWNLOAD_DIR / "%(title).80s.%(ext)s")
    with yt_dlp.YoutubeDL(opts) as ydl:
        dl_info = ydl.extract_info(best_url, download=True)
        if "entries" in dl_info:
            dl_info = dl_info["entries"][0]
        filepath = Path(ydl.prepare_filename(dl_info)).with_suffix(".mp3")

    # 3) tag with best info (source > yt)
    final_title = meta.title or dl_info.get("title") or "Unknown"
    final_artist = meta.artist or dl_info.get("uploader") or "Unknown"

    try:
        audio = MP3(str(filepath))
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TIT2(encoding=3, text=final_title))
        audio.tags.add(TPE1(encoding=3, text=final_artist))
        audio.save()
    except Exception as e:
        logger.warning("Tags failed: %s", e)

    return DownloadResult(
        filepath=filepath,
        title=final_title,
        performer=final_artist,
        duration=int(dl_info.get("duration") or 0),
    )


def _sync_direct(url: str, audio_format: str) -> DownloadResult:
    opts = _ydl_opts(audio_format)
    opts["outtmpl"] = str(DOWNLOAD_DIR / "%(title).80s.%(ext)s")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
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
        logger.warning("Tags failed: %s", e)

    return DownloadResult(
        filepath=filepath,
        title=title,
        performer=performer,
        duration=duration,
    )


# ============================================================
# Public API
# ============================================================

async def download_audio(url: str, audio_format: str = "mp3_320") -> DownloadResult:
    platform = detect_platform(url)

    if platform == Platform.SPOTIFY:
        meta = await _spotify_meta(url)
        if not meta.title:
            raise RuntimeError("Не удалось извлечь метаданные Spotify")
        q = (
            f"ytsearch5:{meta.artist} - {meta.title}"
            if meta.artist else
            f"ytsearch5:{meta.title}"
        )
        logger.info("Spotify meta: artist=%r title=%r dur=%d -> %s",
                    meta.artist, meta.title, meta.duration, q)
        result = await asyncio.to_thread(_sync_search_and_download, q, meta, audio_format)
        result.platform = "spotify"
        return result

    if platform == Platform.YANDEX:
        meta = await _yandex_meta(url)
        if not meta.title:
            raise RuntimeError(
                "Не удалось извлечь метаданные Яндекс.Музыки. "
                "Пришли ссылку на тот же трек в SoundCloud или YouTube."
            )
        q = (
            f"ytsearch5:{meta.artist} - {meta.title}"
            if meta.artist else
            f"ytsearch5:{meta.title}"
        )
        logger.info("Yandex meta: artist=%r title=%r dur=%d -> %s",
                    meta.artist, meta.title, meta.duration, q)
        result = await asyncio.to_thread(_sync_search_and_download, q, meta, audio_format)
        result.platform = "yandex"
        return result

    if platform in (Platform.SOUNDCLOUD, Platform.YOUTUBE):
        result = await asyncio.to_thread(_sync_direct, url, audio_format)
        result.platform = platform.value
        return result

    raise RuntimeError(f"Платформа не поддерживается: {platform.value}")


def cleanup(path: Path) -> None:
    try:
        if path and path.exists():
            path.unlink()
    except Exception as e:
        logger.warning("cleanup failed: %s", e)