"""
تطبيق FastAPI للحصول على روابط التحميل والبحث والترجمة من مكتبة moviebox-api
جاهز للنشر على Vercel
"""

import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from moviebox_api.v3.core import (
    DownloadableVideoFilesDetail,
    DownloadableCaptionFileDetails,
    Search,
)
from moviebox_api.v3.http_client import MovieBoxHttpClient
from moviebox_api.v3.constants import ResolutionType, SubjectType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Server started successfully!")
    yield
    logger.info("🛑 Server shutting down.")


app = FastAPI(
    title="MovieBox FastAPI Backend",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
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
        return cover.get("url") or cover.get("thumbnailUrl") or cover.get("thumbnail_url")
    for attr in ["url", "thumbnailUrl", "thumbnail_url"]:
        val = getattr(cover, attr, None)
        if val:
            return str(val)
    return None


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
    return {
        "subject_id": item.get("subjectId", ""),
        "title": item.get("title", ""),
        "type": "series" if is_series else "movie",
        "poster": get_cover_url(item.get("cover")),
        "year": year,
        "rating": float(item.get("imdbRatingValue") or 0),
        "seasons": season_count,
        "languages": languages,
        "country": item.get("countryName", ""),
        "description": (item.get("description") or "")[:300],
        "has_resource": bool(item.get("hasResource", False)),
    }


def format_download_item(item: dict) -> dict:
    """تحويل dict إلى الصيغة الموحدة"""
    return {
        "url": item.get("resourceLink") or item.get("url"),
        "resolution": item.get("resolution"),
        "size": item.get("size"),
        "season": item.get("se") or item.get("season"),
        "episode": item.get("ep") or item.get("episode"),
        "resource_id": item.get("resourceId") or item.get("resource_id"),
    }


# ─── Core fetch ───────────────────────────────────────────────────────────────

async def fetch_all_pages_for_resolution(
    client: MovieBoxHttpClient,
    subject_id: str,
    resolution: int,
) -> list[dict]:
    """
    يجيب كل الحلقات لـ resolution معين باستخدام get_content_model_all()
    مع تحويل Pydantic model إلى dict بشكل صحيح.
    """
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
                    # نحول الـ Pydantic model إلى dict يدويًا
                    item_dict = {
                        "resourceLink": str(video_file.resource_link) if video_file.resource_link else None,
                        "resolution": int(video_file.resolution) if video_file.resolution else 0,
                        "size": str(video_file.size) if video_file.size else None,
                        "se": int(video_file.season) if video_file.season else 0,
                        "ep": int(video_file.episode) if video_file.episode else 0,
                        "resourceId": str(video_file.resource_id) if video_file.resource_id else None,
                        "extCaptions": [],
                    }
                    items.append(item_dict)

                logger.info(
                    f"📄 {resolution}p — صفحة {page_count}: "
                    f"{len(page_model.list)} حلقة"
                )

            logger.info(f"✅ {resolution}p اكتمل: {len(items)} رابط في {page_count} صفحة")
            return items

        except ValueError as ve:
            logger.warning(
                f"⚠️ {resolution}p: per_page={per_page_val} مرفوض ({ve})"
                f" — بنجرب القيمة التالية"
            )
            continue

        except Exception as e:
            logger.error(f"❌ {resolution}p خطأ: {type(e).__name__}: {e}")
            if per_page_val == PER_PAGE_OPTIONS[-1]:
                return []
            continue

    return []


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/search")
async def search_content(
    query: str = Query(..., description="اسم الفيلم أو المسلسل"),
    original_language: str = Query(None, description="كود اللغة مثل: en, de, ja, ko"),
    limit: int = Query(8, ge=1, le=20),
):
    """بحث MovieBox مستقل تماماً."""
    if not query.strip():
        raise HTTPException(status_code=400, detail="query لا يمكن أن يكون فارغاً")
    try:
        async with MovieBoxHttpClient() as client:
            searcher = Search(
                client_session=client,
                query=query.strip(),
                subject_type=SubjectType.ALL,
            )
            data = await searcher.get_content()

        raw_items = data.get("items", [])
        if not raw_items:
            return JSONResponse(content={
                "status": "success", "query": query,
                "total_results": 0, "results": []
            })

        scored = [(score_result(item, original_language, query), item) for item in raw_items]
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [format_search_item(item) for _, item in scored[:limit]]

        return JSONResponse(content={
            "status": "success", "query": query,
            "total_results": len(results), "results": results
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ خطأ في البحث: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@app.get("/get_download_links")
async def get_download_links(
    subject_id: str = Query(...),
    resolution: int = Query(
        None,
        description="360 | 480 | 720 | 1080 — فارغ = كل الجودات",
    ),
):
    """
    جلب كل روابط التحميل — كل المواسم، كل الحلقات، كل الجودات.
    """
    if not subject_id or not subject_id.strip():
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    if resolution is not None and resolution not in ALL_RESOLUTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"resolution غير صالح. الخيارات: {ALL_RESOLUTIONS}"
        )

    resolutions_to_fetch = [resolution] if resolution is not None else ALL_RESOLUTIONS

    try:
        async with MovieBoxHttpClient() as client:
            tasks = [
                fetch_all_pages_for_resolution(client, subject_id, res)
                for res in resolutions_to_fetch
            ]
            results_per_resolution = await asyncio.gather(*tasks, return_exceptions=True)

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
            raise HTTPException(status_code=404, detail="لم يتم العثور على روابط تحميل")

        download_links.sort(key=lambda x: (
            x.get("season") or 0,
            x.get("episode") or 0,
            x.get("resolution") or 0,
        ))

        seasons = sorted({x["season"] for x in download_links if x.get("season")})
        episodes_per_season: dict = {}
        resolutions_found: set = set()
        for x in download_links:
            s = x.get("season")
            if s:
                episodes_per_season[str(s)] = max(
                    episodes_per_season.get(str(s), 0),
                    x.get("episode") or 0,
                )
            if x.get("resolution"):
                resolutions_found.add(x["resolution"])

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "total_links": len(download_links),
            "seasons_found": seasons,
            "episodes_per_season": episodes_per_season,
            "resolutions_found": sorted(resolutions_found),
            "download_links": download_links,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@app.get("/get_subtitles")
async def get_subtitles(
    subject_id: str = Query(...),
    resource_id: str = Query(..., description="من حقل resource_id في روابط التحميل"),
):
    """
    جلب الترجمات لحلقة معينة عبر resource_id.
    """
    if not subject_id.strip() or not resource_id.strip():
        raise HTTPException(status_code=400, detail="subject_id و resource_id مطلوبان")
    try:
        async with MovieBoxHttpClient() as client:
            caption_fetcher = DownloadableCaptionFileDetails(client_session=client)
            data = await caption_fetcher.get_content(subject_id, resource_id)

        raw_captions = data.get("extCaptions", [])
        all_subtitles = []
        arabic_subtitle = None

        for cap in raw_captions:
            entry = {
                "language_code": cap.get("lan", ""),
                "language_name": cap.get("lanName", ""),
                "url": str(cap.get("url", "")),
                "size": cap.get("size", 0),
                "delay": cap.get("delay", 0),
            }
            all_subtitles.append(entry)
            if cap.get("lan", "").lower() == "ar":
                arabic_subtitle = entry

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "resource_id": resource_id,
            "has_arabic": arabic_subtitle is not None,
            "arabic_subtitle": arabic_subtitle,
            "all_subtitles": all_subtitles,
            "total_languages": len(all_subtitles),
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ خطأ في الترجمة: {e}")
        raise HTTPException(status_code=500, detail=f"Subtitles error: {str(e)}")


@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "healthy", "message": "✅ الخادم يعمل"})


@app.get("/")
async def root():
    return JSONResponse(content={
        "name": "MovieBox FastAPI Backend",
        "version": "7.0",
        "endpoints": {
            "search":                  "/search?query=TITLE&original_language=en&limit=8",
            "get_download_links":      "/get_download_links?subject_id=ID",
            "get_download_links_1res": "/get_download_links?subject_id=ID&resolution=1080",
            "get_subtitles":           "/get_subtitles?subject_id=ID&resource_id=RID",
            "health_check":            "/health",
        },
    })