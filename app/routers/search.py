"""Search and item details endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from moviebox_api.v3.constants import SubjectType
from moviebox_api.v3.core import ItemDetails, Search

from app.core.client import get_client
from app.core.limiter import limiter
from app.utils.formatters import format_search_item, score_result
from app.utils.helpers import get_cover_url, parse_languages

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Search"])


@router.get("/search")
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
        async with get_client() as client:
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


@router.get("/item_details")
@limiter.limit("30/minute")
async def item_details(
    request: Request,
    subject_id: str = Query(..., description="معرف المحتوى (subjectId)"),
    include_seasons: bool = Query(False, description="جلب معلومات المواسم أيضاً"),
):
    """
    جلب تفاصيل فيلم أو مسلسل معين — يستخدم ItemDetails + SeasonDetails.
    يعيد معلومات مثل الوصف، الممثلين، التقييم، المواسم.
    """
    try:
        async with get_client() as client:
            details = ItemDetails(
                client_session=client,
                include_seasons=include_seasons,
            )
            data = await details.get_content(subject_id)

        # Format the response for Android
        item = data.get("item", data)
        seasons_data = data.get("seasons")

        result = {
            "subject_id": item.get("subjectId", ""),
            "title": item.get("title") or item.get("postTitle") or "",
            "description": item.get("description", ""),
            "poster": get_cover_url(item.get("cover")),
            "rating": float(item.get("imdbRatingValue", 0) or 0),
            "year": (item.get("releaseDate", "") or "")[:4],
            "type": "series" if (item.get("seNum", 0) or 0) > 0 else "movie",
            "languages": parse_languages(item.get("language", "")),
            "country": item.get("countryName", ""),
            "genre": (
                [g.strip() for g in item.get("genre", "").split(",") if g.strip()]
                if isinstance(item.get("genre"), str)
                else list(item.get("genre") or [])
            ),
            "seasons_count": item.get("seNum", 0),
            "duration_seconds": item.get("durationSeconds", 0) or 0,
            "has_resource": bool(item.get("hasResource", False)),
        }

        if seasons_data:
            result["seasons"] = seasons_data

        return JSONResponse(content={
            "status": "success",
            "item": result,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Item details error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب تفاصيل المحتوى.",
        )
