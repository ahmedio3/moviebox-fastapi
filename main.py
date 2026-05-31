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
    SeasonDetails,
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

# نجرب per_page كبير عشان نقلل عدد الـ requests
# المكتبة عندها validate_per_page_and_raise — لو رفضت نجرب أصغر
MAX_PER_PAGE = 100
FALLBACK_PER_PAGE = 20

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


def parse_ext_captions(raw_captions: list) -> dict:
    all_subs = []
    arabic_url = None
    for cap in raw_captions:
        if not isinstance(cap, dict):
            continue
        entry = {
            "language_code": cap.get("lan", ""),
            "language_name": cap.get("lanName", ""),
            "url": str(cap.get("url", "")),
        }
        all_subs.append(entry)
        if cap.get("lan", "").lower() == "ar":
            arabic_url = entry["url"]
    return {
        "has_arabic": arabic_url is not None,
        "arabic_url": arabic_url,
        "all": all_subs,
    }


def video_model_to_dict(video_file) -> dict:
    """
    تحويل VideoFileMetadata Pydantic model لـ dict خام
    مع الحفاظ على extCaptions لو موجودة.
    """
    ext_caps = []
    for attr in ["ext_captions", "extCaptions"]:
        val = getattr(video_file, attr, None)
        if val:
            converted = []
            for c in val:
                if isinstance(c, dict):
                    converted.append(c)
                else:
                    converted.append({
                        "lan": getattr(c, "lan", ""),
                        "lanName": getattr(c, "lan_name", getattr(c, "lanName", "")),
                        "url": str(getattr(c, "url", "")),
                        "size": getattr(c, "size", 0),
                        "delay": getattr(c, "delay", 0),
                    })
            ext_caps = converted
            break

    return {
        "resourceLink": str(video_file.url) if video_file.url else None,
        "resolution": video_file.resolution,
        "size": str(video_file.size) if video_file.size else None,
        "se": video_file.season,
        "ep": video_file.episode,
        "resourceId": str(video_file.resource_id) if video_file.resource_id else None,
        "extCaptions": ext_caps,
    }


def format_download_item(item: dict) -> dict:
    raw_ext = item.get("extCaptions") or []
    captions_parsed = parse_ext_captions(raw_ext)
    return {
        "url": item.get("resourceLink"),
        "resolution": item.get("resolution"),
        "size": item.get("size"),
        "season": item.get("se"),
        "episode": item.get("ep"),
        "resource_id": item.get("resourceId"),
        "subtitles_available": captions_parsed["has_arabic"] or len(captions_parsed["all"]) > 0,
        "has_arabic_subtitle": captions_parsed["has_arabic"],
        "arabic_subtitle_url": captions_parsed["arabic_url"],
        "all_subtitles": captions_parsed["all"],
    }


# ─── الدالة الأساسية للجلب ────────────────────────────────────────────────────

async def fetch_all_pages_for_resolution(
    client: MovieBoxHttpClient,
    subject_id: str,
    resolution: int,
) -> list[dict]:
    """
    يجيب كل الحلقات لـ resolution معين — كل الصفحات.

    المشكلة القديمة كانت:
      - الكود كان بيحاول يقرأ pager من dict خام وكان بيفشل
      - نتيجة: has_more = False دايماً → صفحة واحدة بس

    الحل:
      - get_content_model_all() من المكتبة بتتعامل مع pager كـ Pydantic model صح
      - per_page=100 عشان نقلل عدد الـ requests
      - retry تلقائي بـ per_page=20 لو 100 مرفوض
    """
    items = []

    for per_page_val in [MAX_PER_PAGE, FALLBACK_PER_PAGE]:
        items = []
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
                    items.append(video_model_to_dict(video_file))
                logger.info(
                    f"📄 {resolution}p — صفحة {page_count}: "
                    f"{len(page_model.list)} حلقة | "
                    f"has_more={page_model.pager.has_more}"
                )

            logger.info(f"✅ {resolution}p: {len(items)} رابط في {page_count} صفحة")
            break  # نجح

        except ValueError as ve:
            logger.warning(f"⚠️ per_page={per_page_val} مرفوض ({ve}) — بنجرب {FALLBACK_PER_PAGE}")
            if per_page_val == FALLBACK_PER_PAGE:
                logger.error(f"❌ {resolution}p فشل نهائياً")
            continue

        except Exception as e:
            logger.warning(f"⚠️ {resolution}p خطأ: {e}")
            break

    return items


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

    - resolution فارغ  → 360+480+720+1080 بالتوازي مع full pagination
    - resolution محدد  → الجودة دي بس مع full pagination
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

        # دمج + dedup
        seen: set[tuple] = set()
        download_links: list[dict] = []

        for res_idx, result in enumerate(results_per_resolution):
            if isinstance(result, Exception):
                logger.error(
                    f"❌ {resolutions_to_fetch[res_idx]}p exception: {result}"
                )
                continue
            for item in result:
                key = (item.get("se"), item.get("ep"), item.get("resolution"))
                if key in seen:
                    continue
                seen.add(key)
                download_links.append(format_download_item(item))

        if not download_links:
            raise HTTPException(status_code=404, detail="لم يتم العثور على روابط تحميل")

        # ترتيب: موسم ← حلقة ← جودة
        download_links.sort(key=lambda x: (
            x.get("season") or 0,
            x.get("episode") or 0,
            x.get("resolution") or 0,
        ))

        # إحصائيات
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
    جلب الترجمات عبر request منفصل.
    استخدم هذا لو all_subtitles في /get_download_links كان فاضياً.
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
        "version": "5.0",
        "endpoints": {
            "search":                  "/search?query=TITLE&original_language=en&limit=8",
            "get_download_links":      "/get_download_links?subject_id=ID",
            "get_download_links_1res": "/get_download_links?subject_id=ID&resolution=1080",
            "get_subtitles":           "/get_subtitles?subject_id=ID&resource_id=RID",
            "health_check":            "/health",
        },
    })
