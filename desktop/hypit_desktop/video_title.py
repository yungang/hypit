"""Default task theme for a reference video: its web page title when readable, else '<platform>_<video id>'."""
from __future__ import annotations

import html
import re
import urllib.request
from urllib.parse import parse_qs, urlparse

PLATFORM_DOMAINS = [
    ("iesdouyin.com", "抖音"), ("douyin.com", "抖音"),
    ("chenzhongtech.com", "快手"), ("kuaishou.com", "快手"),
    ("weixin.qq.com", "视频号"),
    ("xhslink.com", "小红书"), ("xiaohongshu.com", "小红书"),
    ("yangkeduo.com", "拼多多"), ("pinduoduo.com", "拼多多"),
    ("tiktok.com", "TikTok"),
    ("youtu.be", "YouTube"), ("youtube.com", "YouTube"),
    ("twitter.com", "X"), ("x.com", "X"),
]
# Titles that are really the site's name or a block page, not the video's.
GENERIC_MARKERS = ("验证", "captcha", "access denied", "just a moment", "login", "登录", "403", "404")
TITLE_SUFFIXES = (" - YouTube", " | TikTok", " - 抖音", " - 快手", " - 小红书")
MAX_TITLE = 80


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def platform_of(url: str) -> str:
    host = _host(url)
    for domain, name in PLATFORM_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return name
    return ""


def video_id_of(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("v", "modal_id", "id"):
        if query.get(key):
            return query[key][0]
    segments = [s for s in parsed.path.split("/") if s]
    for segment in reversed(segments):
        if re.fullmatch(r"[\w-]{6,}", segment):
            return segment
    return segments[-1] if segments else ""


def fallback_title(url: str) -> str:
    """'<platform>_<video id>', or the host when the platform is unknown."""
    platform = platform_of(url) or _host(url) or "视频"
    vid = video_id_of(url)
    return f"{platform}_{vid}" if vid else platform


def clean_title(raw: str, url: str) -> str:
    """Normalise a page <title>; '' when it is too generic to name the video."""
    title = re.sub(r"\s+", " ", html.unescape(raw)).strip()
    for suffix in TITLE_SUFFIXES:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    platform = platform_of(url)
    lowered = title.lower()
    if len(title) < 2 or lowered in (platform.lower(), _host(url)):
        return ""
    if any(marker in lowered for marker in GENERIC_MARKERS):
        return ""
    return title[:MAX_TITLE]


def fetch_title(url: str, timeout: float = 5.0) -> str | None:
    """Best effort: read the page title. None when unreachable or only a generic title is served."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(300_000).decode(charset, errors="replace")
    except (OSError, ValueError):
        return None
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    return clean_title(match.group(1), url) or None if match else None
