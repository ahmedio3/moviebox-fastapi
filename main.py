"""
تطبيق FastAPI للحصول على روابط التحميل والبحث من مكتبة moviebox-api
جاهز للنشر على Vercel
"""

import logging
import asyncio
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from moviebox_api.v3.core import DownloadableVideoFilesDetail, Search
from moviebox_api.v3.http_client import MovieBoxHttpClient
from moviebox_api.v3.constants import ResolutionType, SubjectType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MovieBox FastAPI Backend",
    docs_url=None,
    redoc_url=None,
)

RESOLUTIONS = [360, 480, 720, 1080]

# تحويل كود اللغة من TMDB (ISO 639-1) إلى اسم اللغة في MovieBox
TMDB_LANG_MAP: dict[str, list[str]] = {
    "en": ["english"],
    "de": ["german", "deutsch"],
    "ja": ["japanese"],
    "ko": ["korean"],
    "fr": ["french"],
    "es": ["spanish"],
    "ar": ["arabic"],
    "hi": ["hindi"],
    "zh": ["chinese", "mandarin", "cantonese"],
    "it": ["italian"],
    "pt": ["portuguese"],
    "ru": ["russian"],
    "tr": ["turkish"],
    "th": ["thai"],
    "nl": ["dutch"],
    "sv": ["swedish"],
    "da": ["danish"],
    "no": ["norwegian"],
    "fi": ["finnish"],
    "pl": ["polish"],
    "cs": ["czech"],
    "hu": ["hungarian"],
    "ro": ["romanian"],
    "id": ["indonesian"],
    "ms": ["malay"],
    "vi": ["vietnamese"],
}

# كلمات تدل على نسخ مدبلجة (نتجنبها)
DUBBED_KEYWORDS = [
    "hindi", "dubbed", " dub", "tamil", "telugu",
    "malayalam", "kannada", "bengali", "marathi",
    "[hindi]", "(hindi)", "urdu", "punjabi",
]


# ─── Helpers ────────────────────────────────────────────────────────────────

def is_dubbed(title: str) -> bool:
    """كشف النسخ المدبلجة من العنوان"""
    t = title.lower()
    return any(kw in t for kw in DUBBED_KEYWORDS)


def parse_languages(lang_raw) -> list[str]:
    """تحليل حقل اللغة سواء كان string أو list"""
    if isinstance(lang_raw, list):
        return [str(l).strip().lower() for l in lang_raw if l]
    if isinstance(lang_raw, str) and lang_raw:
        return [l.strip().lower() for l in lang_raw.split(",") if l.strip()]
    return []


def get_cover_url(cover) -> str | None:
    """استخراج رابط البوستر بأمان"""
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


def score_result(item: dict, original_language: str | None, query: str) -> int:
    """
    تسجيل نقاط لكل نتيجة بحث لاختيار الأنسب.
    الأعلى نقاطاً يظهر أولاً.
    """
    score = 0
    title = item.get("title", "")

    # عقوبة كبيرة للنسخ المدبلجة
    if is_dubbed(title):
        score -= 200

    # مكافأة تطابق اللغة الأصلية من TMDB
    if original_language:
        target_langs = TMDB_LANG_MAP.get(original_language.lower(), [])
        item_langs = parse_languages(item.get("language", ""))
        if target_langs and any(tl in item_langs for tl in target_langs):
            score += 100

    # مكافأة التطابق الدقيق للعنوان
    if title.lower().strip() == query.lower().strip():
        score += 50
    elif query.lower().strip() in title.lower():
        score += 20

    # مكافأة وجود موارد قابلة للتحميل
    if item.get("hasResource"):
        score += 10

    return score


def format_search_item(item: dict) -> dict:
    """تنسيق عنصر نتيجة البحث للإرسال"""
    release_date = item.get("releaseDate", "") or ""
    year = release_date[:4] if len(release_date) >= 4 else ""

    lang_raw = item.get("language", "")
    if isinstance(lang_raw, str):
        languages = [l.strip() for l in lang_raw.split(",") if l.strip()]
    else:
        languages = [str(l) for l in (lang_raw or [])]

    season_count = item.get("seNum", 0) or 0
    subject_type_val = item.get("subjectType", 0)
    is_series = season_count > 0 or subject_type_val == 2

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


# ─── Subclass يدعم se/ep للمسلسلات ──────────────────────────────────────────

class EpisodeDownload(DownloadableVideoFilesDetail):
    def __init__(self, *args, season: int = None, episode: int = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._season = season
        self._episode = episode

    def _create_params(self, subject_id: str) -> dict:
        params = super()._create_params(subject_id)
        if self._season is not None:
            params["se"] = self._season
        if self._episode is not None:
            params["ep"] = self._episode
        return params


async def fetch_episode_resolution(client, subject_id, season, episode, res_value):
    """جلب حلقة واحدة بجودة محددة"""
    try:
        dl = EpisodeDownload(
            client_session=client,
            resolution=ResolutionType(res_value),
            season=season,
            episode=episode,
        )
        data = await dl.get_content(subject_id)
        return data.get("list", [])
    except Exception as e:
        logger.warning(f"⚠️ S{season}E{episode} @ {res_value}p فشل: {e}")
        return []


# ─── Startup ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Server started successfully!")


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/search")
async def search_content(
    query: str = Query(..., description="اسم الفيلم أو المسلسل"),
    original_language: str = Query(
        None,
        description="كود اللغة الأصلية من TMDB (مثلاً: en, de, ja, ko)"
    ),
    limit: int = Query(8, ge=1, le=20, description="عدد النتائج (1-20)"),
):
    """
    البحث عن فيلم أو مسلسل في MovieBox.
    يرتب النتائج حسب تطابق اللغة الأصلية ويُخفي النسخ المدبلجة.
    """
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
                "status": "success",
                "query": query,
                "total_results": 0,
                "results": [],
            })

        # ترتيب النتائج بالنقاط
        scored = [
            (score_result(item, original_language, query), item)
            for item in raw_items
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        results = [format_search_item(item) for _, item in scored[:limit]]

        return JSONResponse(content={
            "status": "success",
            "query": query,
            "total_results": len(results),
            "results": results,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ خطأ في البحث: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@app.get("/get_download_links")
async def get_download_links(
    subject_id: str = Query(..., description="معرف الفيلم/المسلسل"),
    resolution: int = Query(
        None,
        description="جودة الفيديو (360, 480, 720, 1080) — اتركه فارغاً لكل الجودات"
    ),
):
    """
    جلب روابط التحميل لفيلم أو مسلسل.
    للمسلسلات يجلب كل الحلقات بكل الجودات المتاحة.
    """
    if not subject_id or not subject_id.strip():
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    if resolution is not None:
        try:
            res_enum = ResolutionType(resolution)
        except ValueError:
            res_enum = ResolutionType.UNSPECIFIED
    else:
        res_enum = ResolutionType.UNSPECIFIED

    try:
        async with MovieBoxHttpClient() as client:

            # جلب البيانات الأساسية
            dl = DownloadableVideoFilesDetail(
                client_session=client,
                resolution=res_enum,
            )
            data = await dl.get_content(subject_id)
            base_items = data.get("list", [])

            # هل هو مسلسل؟
            is_series = any(
                item.get("se", 0) != 0 or item.get("ep", 0) != 0
                for item in base_items
            )

            all_items = list(base_items)

            # للمسلسلات: جلب كل حلقة بكل جودة بالتوازي
            if is_series and res_enum == ResolutionType.UNSPECIFIED:
                episodes = [
                    (item.get("se", 0), item.get("ep", 0))
                    for item in base_items
                ]

                tasks = [
                    fetch_episode_resolution(client, subject_id, se, ep, res)
                    for res in RESOLUTIONS[1:]   # 480, 720, 1080
                    for (se, ep) in episodes
                ]

                results = await asyncio.gather(*tasks)

                for chunk in results:
                    all_items.extend(chunk)

        # تجميع النتائج وإزالة المكررات
        download_links = []
        seen: set[tuple] = set()

        for item in all_items:
            key = (item.get("se"), item.get("ep"), item.get("resolution"))
            if key in seen:
                continue
            seen.add(key)
            download_links.append({
                "url": item.get("resourceLink"),
                "resolution": item.get("resolution"),
                "size": item.get("size"),
                "season": item.get("se"),
                "episode": item.get("ep"),
            })

        if not download_links:
            raise HTTPException(
                status_code=404,
                detail="لم يتم العثور على روابط تحميل لهذا المحتوى"
            )

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "total_links": len(download_links),
            "download_links": download_links,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "healthy", "message": "✅ الخادم يعمل"})


@app.get("/")
async def root():
    return JSONResponse(content={
        "name": "MovieBox FastAPI Backend",
        "version": "2.0",
        "endpoints": {
            "search": "/search?query=TITLE&original_language=en&limit=8",
            "get_download_links": "/get_download_links?subject_id=ID&resolution=1080",
            "health_check": "/health",
        },
    })
