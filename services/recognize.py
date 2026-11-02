"""Распознавание музыки через Shazam (shazamio) с конвертацией в WAV."""
import asyncio
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from shazamio import Shazam
    _SHAZAM_AVAILABLE = True
except ImportError:
    _SHAZAM_AVAILABLE = False
    logger.warning("shazamio не установлен - распознавание отключено")

FFMPEG_LOCATION = os.getenv("FFMPEG_LOCATION", "").strip() or "ffmpeg"


def _convert_to_wav(input_path: Path, output_path: Path) -> bool:
    try:
        result = subprocess.run(
            [
                FFMPEG_LOCATION, "-y",
                "-i", str(input_path),
                "-ac", "1",
                "-ar", "44100",
                "-sample_fmt", "s16",
                "-t", "15",
                str(output_path),
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="ignore")
            logger.error("ffmpeg failed: %s", stderr[-500:])
            return False
        return output_path.exists() and output_path.stat().st_size > 1000
    except Exception:
        logger.exception("ffmpeg conversion failed")
        return False


async def _do_recognize(shazam: "Shazam", path: Path) -> dict | None:
    out = await shazam.recognize(str(path))
    if not out or not out.get("track"):
        return None
    track = out["track"]
    return {
        "title": track.get("title", ""),
        "artist": track.get("subtitle", ""),
        "url": track.get("url", ""),
    }


async def recognize_file(audio_path: Path) -> dict | None:
    if not _SHAZAM_AVAILABLE:
        return None

    wav_path = audio_path.with_suffix(".wav")
    used_wav = False
    shazam = None
    try:
        ok = await asyncio.to_thread(_convert_to_wav, audio_path, wav_path)
        used_wav = ok
        if not ok:
            logger.warning("WAV conversion failed, trying original file")

        target = wav_path if used_wav else audio_path
        shazam = Shazam()
        try:
            return await _do_recognize(shazam, target)
        finally:
            # Закрываем внутреннюю aiohttp-сессию
            try:
                close = getattr(shazam, "close", None)
                if close:
                    r = close()
                    if asyncio.iscoroutine(r):
                        await r
            except Exception as e:
                logger.debug("shazam close failed: %s", e)
    except Exception:
        logger.exception("shazam recognize failed")
        return None
    finally:
        if used_wav and wav_path.exists():
            try:
                wav_path.unlink()
            except Exception:
                pass