import hashlib
from urllib.parse import urlparse, urlunparse, parse_qs


def normalize_url(url: str) -> str:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        qs = parse_qs(p.query)
        v = qs.get("v", [None])[0]
        return urlunparse((p.scheme, p.netloc, p.path, "", f"v={v}" if v else "", ""))
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:32]