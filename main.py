"""
تطبيق FastAPI للحصول على روابط التحميل والبحث والترجمة من مكتبة moviebox-api v3
جاهز للنشر على Vercel

Compatible with Watchera Android client contract.
"""

import logging
import asyncio
import time
from contextlib import asynccontextmanager
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from moviebox_api.v3.core import (
    DownloadableVideoFilesDetail,
    DownloadableCaptionFileDetails,
    Search,
)
from moviebox_api.v3.http_client import MovieBoxHttpClient
from moviebox_api.v3.constants import ResolutionType, SubjectType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─── Rate Limiter ────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Watchera MovieBox API started")
    yield
    logger.info("🛑 Shutting down")


app = FastAPI(
    title="MovieBox FastAPI Backend for Watchera",
    version="8.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "status": "error",
            "error": "rate_limit_exceeded",
            "message": "تجاوزت الحد المسموح من الطلبات، حاول بعد دقيقة.",
        },
    )


ALL_RESOLUTIONS = [360, 480, 720, 1080]
PER_PAGE_OPTIONS = [100, 20]

TMDB_LANG_MAP: dict[str, list[str]] = {
    "en": ["english"], "de": ["german", "deutsch"], "ja": ["japanese"],
    "ko": ["korean"], "fr": ["french"], "es": ["spanish"], "ar": ["arabic"],
    "hi": ["hindi"], "zh": ["chinese", "mandarin", "cantonese"],
    "it": ["italian"], "pt": ["portuguese"], "ru": ["russian"],
    "tr": ["turkish"], "th": ["thai"], "nl": ["dutch"], "sv": ["swedish"],
    "da": ["danish"], "no": ["norwegian"], "fi": ["finnish"],
    "pl": ["polish"], "cs": ["czech"], "hu": ["hungarian"],
    "ro": ["romanian"], "id": ["indonesian"], "ms": ["malay"],
    "vi": ["vietnamese"],
}

DUBBED_KEYWORDS = [
    "hindi", "dubbed", " dub", "tamil", "telugu", "malayalam",
    "kannada", "bengali", "marathi", "[hindi]", "(hindi)", "urdu", "punjabi",
]

ARABIC_LAN_CODES = {"ar", "ara", "arabic"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

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

    return {
        "url": item.get("resourceLink") or item.get("url"),
        "resolution": int(item.get("resolution") or 0),
        "size": item.get("size"),
        "season": int(item.get("se") or item.get("season") or 0),
        "episode": int(item.get("ep") or item.get("episode") or 0),
        "resource_id": item.get("resourceId") or item.get("resource_id") or "",
        "codec": item.get("codecName"),
        "duration": int(item.get("duration") or 0),
        "source_url": item.get("sourceUrl"),
        **sub_info,
    }


# ─── Core fetch ──────────────────────────────────────────────────────────────

async def fetch_all_pages_for_resolution(
    client: MovieBoxHttpClient,
    subject_id: str,
    resolution: int,
) -> list[dict]:
    """يجيب كل الحلقات لـ resolution معين مع استخراج الـ captions كمان."""
    for per_page_val in PER_PAGE_OPTIONS:
        items: list[dict] = []
        try:
            res_enum = ResolutionType(resolution)
            dl = DownloadableVideoFilesDetail(
                client_session=client,
                resolution=res_enum,
                per_page=per_page_val,
            )

            page_count = 0
            async for page_model in dl.get_content_model_all(subject_id):
                page_count += 1
                for video_file in page_model.list:
                    ext_caps = video_file.ext_captions or []
                    item_dict = {
                        "resourceLink": str(video_file.resource_link) if video_file.resource_link else None,
                        "resolution": int(video_file.resolution) if video_file.resolution else 0,
                        "size": str(video_file.size) if video_file.size else None,
                        "se": int(video_file.season) if video_file.season else 0,
                        "ep": int(video_file.episode) if video_file.episode else 0,
                        "resourceId": str(video_file.resource_id) if video_file.resource_id else None,
                        "codecName": getattr(video_file, "codec_name", None) or getattr(video_file, "codecName", None),
                        "duration": int(getattr(video_file, "duration", 0) or 0),
                        "sourceUrl": str(getattr(video_file, "source_url", "") or "") or None,
                        # ── الترجمات المضمنة مع الملف (إن وجدت) ──
                        "extCaptions": [
                            {
                                "id": getattr(cap, "id", ""),
                                "lan": getattr(cap, "lan", "") or "",
                                "lanName": getattr(cap, "lan_name", "") or "",
                                "url": str(getattr(cap, "url", "") or ""),
                                "size": int(getattr(cap, "size", 0) or 0),
                                "delay": int(getattr(cap, "delay", 0) or 0),
                            }
                            for cap in ext_caps
                        ],
                    }
                    items.append(item_dict)

                logger.info(
                    f"📄 {resolution}p — page {page_count}: {len(page_model.list)} items"
                )

            logger.info(f"✅ {resolution}p done: {len(items)} links in {page_count} pages")
            return items

        except ValueError as ve:
            logger.warning(
                f"⚠️ {resolution}p: per_page={per_page_val} rejected ({ve}) — trying next"
            )
            continue

        except Exception as e:
            logger.error(f"❌ {resolution}p error: {type(e).__name__}: {e}")
            if per_page_val == PER_PAGE_OPTIONS[-1]:
                return []
            continue

    return []


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/search")
@limiter.limit("30/minute")
async def search_content(
    request: Request,
    query: str = Query(..., description="اسم الفيلم أو المسلسل"),
    original_language: str = Query(None, description="كود اللغة مثل: en, de, ja, ko"),
    limit: int = Query(8, ge=1, le=20),
):
    """بحث في MovieBox — متوافق مع MovieBoxApiImpl.search في Android."""
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query لا يمكن أن يكون فارغاً")
    try:
        async with MovieBoxHttpClient() as client:
            searcher = Search(
                client_session=client,
                query=query,
                subject_type=SubjectType.ALL,
            )
            data = await searcher.get_content()

        raw_items = data.get("items", [])
        if not raw_items:
            return JSONResponse(content={
                "status": "success", "query": query,
                "total_results": 0, "results": []
            })

        scored = [
            (score_result(item, original_language, query), item)
            for item in raw_items
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [format_search_item(item) for _, item in scored[:limit]]

        return JSONResponse(content={
            "status": "success", "query": query,
            "total_results": len(results), "results": results,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Search error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في البحث. حاول مرة أخرى.",
        )


@app.get("/get_download_links")
@limiter.limit("20/minute")
async def get_download_links(
    request: Request,
    subject_id: str = Query(...),
    resolution: int = Query(
        None,
        description="360 | 480 | 720 | 1080 — empty = all qualities",
    ),
):
    """
    جلب كل روابط التحميل — مع الترجمات المضمنة (subtitles_available,
    has_arabic_subtitle, arabic_subtitle_url, all_subtitles).
    """
    if not subject_id or not subject_id.strip():
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    if resolution is not None and resolution not in ALL_RESOLUTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"resolution غير صالح. الخيارات: {ALL_RESOLUTIONS}",
        )

    resolutions_to_fetch = [resolution] if resolution is not None else ALL_RESOLUTIONS

    try:
        async with MovieBoxHttpClient() as client:
            tasks = [
                fetch_all_pages_for_resolution(client, subject_id, res)
                for res in resolutions_to_fetch
            ]
            results_per_resolution = await asyncio.gather(
                *tasks, return_exceptions=True
            )

        seen: set[tuple] = set()
        download_links: list[dict] = []

        for res_idx, result in enumerate(results_per_resolution):
            if isinstance(result, Exception):
                logger.error(
                    f"❌ {resolutions_to_fetch[res_idx]}p exception: {result}"
                )
                continue
            for raw_item in result:
                formatted = format_download_item(raw_item)
                # لو الـ ext_captions فاضية، نعمل fallback للـ get_subtitles
                if not formatted["subtitles_available"] and formatted["resource_id"]:
                    try:
                        cap_fetcher = DownloadableCaptionFileDetails(client_session=client)
                        cap_data = await cap_fetcher.get_content(subject_id, formatted["resource_id"])
                        raw_caps = cap_data.get("extCaptions", [])
                        if raw_caps:
                            sub_info = build_subtitle_summary(raw_caps)
                            formatted.update(sub_info)
                    except Exception as e:
                        logger.warning(f"⚠️ subtitle fallback failed for {formatted['resource_id']}: {e}")
                key = (
                    formatted.get("season"),
                    formatted.get("episode"),
                    formatted.get("resolution"),
                )
                if key in seen:
                    continue
                seen.add(key)
                download_links.append(formatted)

        if not download_links:
            raise HTTPException(
                status_code=404, detail="لم يتم العثور على روابط تحميل"
            )

        download_links.sort(key=lambda x: (
            x.get("season") or 0,
            x.get("episode") or 0,
            -(x.get("resolution") or 0),
        ))

        seasons = sorted({x["season"] for x in download_links if x.get("season")})
        episodes_per_season: dict = defaultdict(int)
        resolutions_found: set = set()
        any_arabic = False
        for x in download_links:
            s = x.get("season")
            if s:
                episodes_per_season[str(s)] = max(
                    episodes_per_season[str(s)], x.get("episode") or 0
                )
            if x.get("resolution"):
                resolutions_found.add(x["resolution"])
            if x.get("has_arabic_subtitle"):
                any_arabic = True

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "total_links": len(download_links),
            "seasons_found": seasons,
            "episodes_per_season": dict(episodes_per_season),
            "resolutions_found": sorted(resolutions_found),
            "has_arabic_subtitles": any_arabic,
            "download_links": download_links,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Download links error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب الروابط. حاول مرة أخرى.",
        )


@app.get("/get_subtitles")
@limiter.limit("60/minute")
async def get_subtitles(
    request: Request,
    subject_id: str = Query(...),
    resource_id: str = Query(..., description="من حقل resource_id في روابط التحميل"),
):
    """
    جلب الترجمات لحلقة معينة عبر resource_id — endpoint احتياطي.
    """
    if not subject_id.strip() or not resource_id.strip():
        raise HTTPException(
            status_code=400, detail="subject_id و resource_id مطلوبان"
        )
    try:
        async with MovieBoxHttpClient() as client:
            caption_fetcher = DownloadableCaptionFileDetails(client_session=client)
            data = await caption_fetcher.get_content(subject_id, resource_id)

        raw_captions = data.get("extCaptions", [])
        sub_info = build_subtitle_summary(raw_captions)
        arabic_sub = next(
            (s for s in sub_info["all_subtitles"] if is_arabic_caption(s)), None
        )

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "resource_id": resource_id,
            "has_arabic": arabic_sub is not None,
            "arabic_subtitle": arabic_sub,
            "all_subtitles": sub_info["all_subtitles"],
            "total_languages": sub_info["total_languages"],
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Subtitles error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب الترجمات.",
        )


@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "healthy", "service": "watchera-moviebox"})


@app.get("/")
async def root():
    return JSONResponse(content={
        "name": "MovieBox FastAPI Backend for Watchera",
        "version": "8.0",
        "endpoints": {
            "search":                  "/search?query=TITLE&original_language=en&limit=8",
            "get_download_links":      "/get_download_links?subject_id=ID",
            "get_download_links_1res": "/get_download_links?subject_id=ID&resolution=1080",
            "get_subtitles":           "/get_subtitles?subject_id=ID&resource_id=RID",
            "health":                  "/health",
        },
        "rate_limits": {
            "search": "30/minute",
            "get_download_links": "20/minute",
            "get_subtitles": "60/minute",
        },
    })
