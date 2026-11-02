import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from shazamio import Shazam
    _SHAZAM_AVAILABLE = True
except ImportError:
    _SHAZAM_AVAILABLE = False
    logger.warning("shazamio не установлен — распознавание отключено")


async def recognize_file(audio_path: Path) -> dict | None:
    if not _SHAZAM_AVAILABLE:
        return None
    try:
        shazam = Shazam()
        out = await shazam.recognize(str(audio_path))
        if not out or not out.get("track"):
            return None
        track = out["track"]
        return {
            "title": track.get("title", ""),
            "artist": track.get("subtitle", ""),
            "url": track.get("url", ""),
        }
    except Exception:
        logger.exception("shazam recognize failed")
        return None