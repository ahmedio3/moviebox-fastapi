"""Discovery endpoints for trending, browsing, and random recommendations."""

import logging
import random

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from moviebox_api.v3.constants import SubjectType
from moviebox_api.v3.core import Homepage, Search

from app.core.client import get_client
from app.core.limiter import limiter
from app.utils.formatters import format_search_item
from app.utils.helpers import is_adult

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Discover"])


@router.get("/trending")
@limiter.limit("15/minute")
async def trending_content(
    request: Request,
    tab: str = Query("all", description="all | movie | tv | anime — تبويب المحتوى"),
    page: int = Query(1, ge=1, description="رقم الصفحة"),
    safe_mode: bool = Query(True, description="تصفية المحتوى الغير لائق (+18, xxx, adult)"),
    limit: int = Query(20, ge=1, le=50, description="عدد النتائج"),
):
    """
    جلب المحتوى الرائج من الصفحة الرئيسية لمكتبة MovieBox — باستخدام Homepage class.
    يدعم التبويبات: all, movie, tv, anime.
    """
    tab_map = {
        "all": 0,
        "movie": 2,
        "tv": 5,
        "anime": 8,
    }
    tab_id = tab_map.get(tab.lower(), 0)

    try:
        async with get_client() as client:
            homepage = Homepage(client_session=client)
            homepage._page_number = page
            homepage._tab_id = tab_id
            data = await homepage.get_content()

        raw_items = data.get("items", [])
        if not raw_items:
            return JSONResponse(content={
                "status": "success", "total_results": 0, "results": []
            })

        # Extract items directly or from section subjects
        flat_items: list[dict] = []
        for it in raw_items:
            if it.get("subjectId") and str(it.get("subjectId", "")).strip():
                flat_items.append(it)
            for sub in it.get("subjects", []) or []:
                if sub.get("subjectId") and str(sub.get("subjectId", "")).strip():
                    flat_items.append(sub)

        # Deduplicate
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for it in flat_items:
            sid = str(it.get("subjectId"))
            if sid not in seen_ids:
                seen_ids.add(sid)
                deduped.append(it)
        raw_items = deduped

        # Filter safe mode
        if safe_mode:
            raw_items = [item for item in raw_items if not is_adult(item)]

        results = [format_search_item(item) for item in raw_items]
        paginated = results[:limit]

        return JSONResponse(content={
            "status": "success",
            "tab": tab,
            "total_results": len(paginated),
            "results": paginated,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Trending error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب المحتوى الرائج.",
        )


@router.get("/browse")
@limiter.limit("15/minute")
async def browse_content(
    request: Request,
    genre: str = Query(None, description="نوع المحتوى (مفصول بفواصل) مثل: action,drama"),
    type: str = Query("all", description="movie أو series أو all"),
    sort: str = Query("rating", description="rating أو newest أو oldest أو random"),
    safe_mode: bool = Query(True, description="تصفية المحتوى الغير لائق (+18, xxx, adult)"),
    limit: int = Query(20, ge=1, le=50, description="عدد النتائج"),
):
    """تصفح المحتوى مع فلاتر متعددة — متوافق مع MovieBoxSearchResult."""
    valid_types = {"movie", "series", "all"}
    valid_sorts = {"rating", "newest", "oldest", "random"}
    if type not in valid_types:
        raise HTTPException(status_code=400, detail="type يجب أن يكون movie أو series أو all")
    if sort not in valid_sorts:
        raise HTTPException(status_code=400, detail="sort يجب أن يكون rating أو newest أو oldest أو random")

    try:
        queries: list[str]
        if genre:
            queries = [g.strip() for g in genre.split(",") if g.strip()]
        else:
            queries = ["2024", "new", "popular", "action", "comedy", "drama", "top"]

        all_items: list[dict] = []
        async with get_client() as client:
            for q in queries:
                searcher = Search(
                    client_session=client,
                    query=q,
                    subject_type=SubjectType.ALL,
                )
                data = await searcher.get_content()
                items = data.get("items", [])
                all_items.extend(items)

        if not all_items:
            return JSONResponse(content={
                "status": "success", "total_results": 0, "results": []
            })

        seen_ids: set[str] = set()
        unique_items: list[dict] = []
        for item in all_items:
            sid = item.get("subjectId", "")
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                unique_items.append(item)

        filtered: list[dict] = unique_items

        if type == "movie":
            filtered = [
                item for item in filtered
                if not ((item.get("seNum", 0) or 0) > 0 or item.get("subjectType", 0) == 2)
            ]
        elif type == "series":
            filtered = [
                item for item in filtered
                if (item.get("seNum", 0) or 0) > 0 or item.get("subjectType", 0) == 2
            ]

        if genre:
            genre_filter = [g.strip().lower() for g in genre.split(",") if g.strip()]

            def _genre_match(item: dict) -> bool:
                raw = item.get("genre", "")
                if isinstance(raw, str):
                    item_genres = [g.strip().lower() for g in raw.split(",") if g.strip()]
                else:
                    item_genres = [str(g).lower() for g in (raw or [])]
                return any(g in item_genres for g in genre_filter)

            filtered = [item for item in filtered if _genre_match(item)]

        if safe_mode:
            filtered = [item for item in filtered if not is_adult(item)]

        results = [format_search_item(item) for item in filtered]

        if sort == "rating":
            results.sort(key=lambda x: x.get("rating", 0) or 0, reverse=True)
        elif sort == "newest":
            results.sort(key=lambda x: x.get("year", "") or "", reverse=True)
        elif sort == "oldest":
            results.sort(key=lambda x: x.get("year", "") or "")
        elif sort == "random":
            random.shuffle(results)

        paginated = results[:limit]

        return JSONResponse(content={
            "status": "success",
            "total_results": len(results),
            "results": paginated,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Browse error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في تصفح المحتوى.",
        )


@router.get("/random")
@limiter.limit("15/minute")
async def random_content(
    request: Request,
    type: str = Query("all", description="movie أو series أو all"),
    safe_mode: bool = Query(True, description="تصفية المحتوى الغير لائق"),
    limit: int = Query(1, ge=1, le=10, description="عدد العناصر العشوائية"),
):
    """جلب محتوى عشوائي — متوافق مع MovieBoxSearchResult."""
    valid_types = {"movie", "series", "all"}
    if type not in valid_types:
        raise HTTPException(status_code=400, detail="type يجب أن يكون movie أو series أو all")

    try:
        queries = ["2024", "2025", "new", "popular", "action", "comedy", "drama", "top"]
        all_items: list[dict] = []

        random.shuffle(queries)

        async with get_client() as client:
            for q in queries:
                searcher = Search(
                    client_session=client,
                    query=q,
                    subject_type=SubjectType.ALL,
                )
                data = await searcher.get_content()
                items = data.get("items", [])
                all_items.extend(items)
                if len(all_items) >= 50:
                    break

        if not all_items:
            return JSONResponse(content={
                "status": "success", "total_results": 0, "results": []
            })

        seen_ids: set[str] = set()
        unique_items: list[dict] = []
        for item in all_items:
            sid = item.get("subjectId", "")
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                unique_items.append(item)

        filtered: list[dict] = unique_items

        if type == "movie":
            filtered = [
                item for item in filtered
                if not ((item.get("seNum", 0) or 0) > 0 or item.get("subjectType", 0) == 2)
            ]
        elif type == "series":
            filtered = [
                item for item in filtered
                if (item.get("seNum", 0) or 0) > 0 or item.get("subjectType", 0) == 2
            ]

        if safe_mode:
            filtered = [item for item in filtered if not is_adult(item)]

        random.shuffle(filtered)
        picked = filtered[:limit]
        results = [format_search_item(item) for item in picked]

        return JSONResponse(content={
            "status": "success",
            "total_results": len(results),
            "results": results,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Random error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب المحتوى العشوائي.",
        )
