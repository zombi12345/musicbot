"""Определение музыкальной платформы по URL."""
import re
from enum import Enum


class Platform(Enum):
    SPOTIFY = "spotify"
    SOUNDCLOUD = "soundcloud"
    YANDEX = "yandex"
    YOUTUBE = "youtube"
    UNKNOWN = "unknown"


PATTERNS = [
    (Platform.SPOTIFY, [
        r"open\.spotify\.com/(?:track|album|playlist|intl-[a-z]+/track)/",
    ]),
    (Platform.SOUNDCLOUD, [
        r"soundcloud\.com/",
        r"on\.soundcloud\.com/",
    ]),
    (Platform.YANDEX, [
        r"music\.yandex\.(?:ru|com|by|kz|uz)/",
    ]),
    (Platform.YOUTUBE, [
        r"(?:www\.)?youtube\.com/(?:watch|shorts)",
        r"youtu\.be/",
        r"music\.youtube\.com/",
    ]),
]


def detect_platform(url: str) -> Platform:
    if not url:
        return Platform.UNKNOWN
    for platform, patterns in PATTERNS:
        for p in patterns:
            if re.search(p, url, re.IGNORECASE):
                return platform
    return Platform.UNKNOWN


def is_supported(url: str) -> bool:
    return detect_platform(url) != Platform.UNKNOWN