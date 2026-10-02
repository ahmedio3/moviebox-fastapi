"""Helper and classification functions for content inspection."""

from app.config import (
    ADULT_KEYWORDS,
    ARABIC_LAN_CODES,
    DUBBED_KEYWORDS,
    DUMMY_VIDEO_HASH,
)


def is_dubbed(title: str) -> bool:
    return any(kw in title.lower() for kw in DUBBED_KEYWORDS)


def parse_languages(lang_raw) -> list[str]:
    if isinstance(lang_raw, list):
        return [str(l).strip().lower() for l in lang_raw if l]
    if isinstance(lang_raw, str) and lang_raw:
        return [l.strip().lower() for l in lang_raw.split(",") if l.strip()]
    return []


def get_cover_url(cover) -> str | None:
    if not cover:
        return None
    if isinstance(cover, dict):
        return (
            cover.get("url")
            or cover.get("thumbnailUrl")
            or cover.get("thumbnail_url")
        )
    for attr in ["url", "thumbnailUrl", "thumbnail_url"]:
        val = getattr(cover, attr, None)
        if val:
            return str(val)
    return None


def is_arabic_caption(caption: dict | object) -> bool:
    """يكتشف لو الترجمة عربية من الـ language code أو الاسم."""
    lan = ""
    lan_name = ""
    if isinstance(caption, dict):
        lan = (caption.get("lan") or caption.get("language_code") or "").lower()
        lan_name = (caption.get("lanName") or caption.get("language_name") or "").lower()
    else:
        lan = (getattr(caption, "lan", "") or "").lower()
        lan_name = (getattr(caption, "lan_name", "") or "").lower()
    if lan in ARABIC_LAN_CODES:
        return True
    if "arab" in lan_name:
        return True
    return False


def is_adult(item: dict) -> bool:
    """يتحقق إذا كان المحتوى غير لائق (+18, adult, hentai, xxx, إلخ)."""
    title = (item.get("title", "") or "").lower()
    genre_raw = item.get("genre", "")
    if isinstance(genre_raw, str):
        genre_list = [g.strip().lower() for g in genre_raw.split(",") if g.strip()]
    else:
        genre_list = [str(g).lower() for g in (genre_raw or [])]
    for kw in ADULT_KEYWORDS:
        if kw in title:
            return True
        for g in genre_list:
            if kw in g:
                return True
    return False


def is_dummy_video(url: str | None) -> bool:
    if not url:
        return False
    return DUMMY_VIDEO_HASH in str(url)
