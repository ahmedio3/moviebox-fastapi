"""Formatters to ensure backward-compatible JSON payloads with the Watchera Android client."""

from app.config import TMDB_LANG_MAP
from app.utils.helpers import (
    get_cover_url,
    is_arabic_caption,
    is_dubbed,
    parse_languages,
)


def format_caption(caption) -> dict:
    """يحوّل CaptionFileMetadata أو dict لـ صيغة موحدة."""
    if isinstance(caption, dict):
        return {
            "language_code": caption.get("lan") or caption.get("language_code", ""),
            "language_name": caption.get("lanName") or caption.get("language_name", ""),
            "url": str(caption.get("url", "")),
            "size": int(caption.get("size", 0) or 0),
            "delay": int(caption.get("delay", 0) or 0),
        }
    return {
        "language_code": getattr(caption, "lan", "") or "",
        "language_name": getattr(caption, "lan_name", "") or "",
        "url": str(getattr(caption, "url", "") or ""),
        "size": int(getattr(caption, "size", 0) or 0),
        "delay": int(getattr(caption, "delay", 0) or 0),
    }


def build_subtitle_summary(raw_captions: list) -> dict:
    """يحوّل قائمة captions لـ dict فيه معلومات الـ frontend محتاجها."""
    all_subs = [format_caption(c) for c in (raw_captions or []) if c]
    all_subs = [s for s in all_subs if s["url"]]

    arabic_sub = next(
        (s for s in all_subs if is_arabic_caption(s)), None
    )

    return {
        "subtitles_available": len(all_subs) > 0,
        "has_arabic_subtitle": arabic_sub is not None,
        "arabic_subtitle_url": arabic_sub["url"] if arabic_sub else None,
        "all_subtitles": all_subs,
        "total_languages": len(all_subs),
    }


def score_result(item: dict, original_language: str | None, query: str) -> int:
    score = 0
    title = item.get("title", "")
    if is_dubbed(title):
        score -= 200
    if original_language:
        target_langs = TMDB_LANG_MAP.get(original_language.lower(), [])
        item_langs = parse_languages(item.get("language", ""))
        if target_langs and any(tl in item_langs for tl in target_langs):
            score += 100
    if title.lower().strip() == query.lower().strip():
        score += 50
    elif query.lower().strip() in title.lower():
        score += 20
    if item.get("hasResource"):
        score += 10
    return score


def format_search_item(item: dict) -> dict:
    """صيغة البحث - متوافقة مع MovieBoxSearchResult في Android."""
    release_date = item.get("releaseDate", "") or ""
    year = release_date[:4] if len(release_date) >= 4 else ""
    lang_raw = item.get("language", "")
    languages = (
        [l.strip() for l in lang_raw.split(",") if l.strip()]
        if isinstance(lang_raw, str)
        else [str(l) for l in (lang_raw or [])]
    )
    season_count = item.get("seNum", 0) or 0
    is_series = season_count > 0 or item.get("subjectType", 0) == 2

    duration_seconds = item.get("durationSeconds", 0) or 0

    return {
        "subject_id": item.get("subjectId", ""),
        "title": item.get("title", ""),
        "type": "series" if is_series else "movie",
        "poster": get_cover_url(item.get("cover")),
        "year": year,
        "rating": float(item.get("imdbRatingValue") or 0),
        "seasons": season_count,
        "duration_seconds": duration_seconds,
        "languages": languages,
        "country": item.get("countryName", ""),
        "description": (item.get("description") or "")[:300],
        "genre": (
            [g.strip() for g in item.get("genre", "").split(",") if g.strip()]
            if isinstance(item.get("genre"), str)
            else list(item.get("genre") or [])
        ),
        "has_resource": bool(item.get("hasResource", False)),
    }


def format_download_item(item: dict) -> dict:
    """صيغة رابط التحميل الواحد - متوافقة مع VideoFile في Android."""
    raw_captions = item.get("extCaptions", []) or []
    sub_info = build_subtitle_summary(raw_captions)

    url_val = item.get("resourceLink") or item.get("url")
    return {
        "url": url_val,
        "resolution": int(item.get("resolution") or 0),
        "size": item.get("size"),
        "season": int(item.get("se") or item.get("season") or 0),
        "episode": int(item.get("ep") or item.get("episode") or 0),
        "resource_id": item.get("resourceId") or item.get("resource_id") or "",
        "codec": item.get("codecName") or item.get("codec"),
        "duration": int(item.get("duration") or 0),
        "source_url": item.get("sourceUrl"),
        "stream_type": item.get(
            "stream_type", "dash" if (url_val and ".mpd" in url_val) else "mp4"
        ),
        "cookie": item.get("cookie"),
        "headers": item.get("headers"),
        "resolutions_available": item.get("resolutions_available"),
        **sub_info,
    }
