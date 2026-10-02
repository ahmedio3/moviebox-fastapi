"""Adult content endpoints and keyword registry."""

import asyncio
import logging
import random

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from moviebox_api.v3.constants import SubjectType
from moviebox_api.v3.core import Homepage, Search

from app.config import ADULT_QUERIES
from app.core.client import get_client
from app.core.limiter import limiter
from app.utils.formatters import format_search_item
from app.utils.helpers import is_adult

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Adult"])


@router.get("/adult")
@limiter.limit("10/minute")
async def adult_content(
    request: Request,
    type: str = Query("all", description="movie | series | all"),
    queries: str = Query("", description="الكلمات المفتاحية مفصولة بفاصلة (اختياري)"),
    limit: int = Query(10, ge=1, le=60, description="عدد النتائج"),
    sort: str = Query("random", description="random | rating | newest"),
):
    """
    جلب محتوى +18 باستخدام الكلمات المفتاحية اللي يختارها المستخدم.
    لو queries فاضي، يستخدم أول 5 كلمات افتراضياً.
    """
    valid_types = {"movie", "series", "all"}
    if type not in valid_types:
        raise HTTPException(status_code=400, detail="type يجب أن يكون movie أو series أو all")

    # Parse selected queries
    if queries and queries.strip():
        selected = [q.strip() for q in queries.split(",") if q.strip()]
    else:
        selected = ADULT_QUERIES[:5]  # default: first 5

    # Limit to max 10 keywords
    if len(selected) > 10:
        selected = selected[:10]

    try:
        all_items: list[dict] = []
        async with get_client() as client:

            # 1. Search all selected keywords CONCURRENTLY
            async def search_keyword(q: str) -> list[dict]:
                try:
                    searcher = Search(
                        client_session=client,
                        query=q,
                        subject_type=SubjectType.ALL,
                    )
                    data = await asyncio.wait_for(
                        searcher.get_content(), timeout=8.0
                    )
                    return data.get("items", [])
                except Exception:
                    return []

            tasks = [search_keyword(q) for q in selected]
            results_lists = await asyncio.gather(*tasks)
            for items in results_lists:
                all_items.extend(items)

            # 2. Also fetch from Anime tab (often contains mature content)
            try:
                homepage = Homepage(client_session=client)
                homepage._page_number = 1
                homepage._tab_id = 8
                anime_data = await asyncio.wait_for(
                    homepage.get_content(), timeout=8.0
                )
                anime_items = anime_data.get("items", [])
                for item in anime_items:
                    if is_adult(item):
                        all_items.append(item)
            except Exception:
                pass

        if not all_items:
            return JSONResponse(content={
                "status": "success", "total_results": 0, "results": []
            })

        # Deduplicate + filter empty subjectId
        seen_ids: set[str] = set()
        unique_items: list[dict] = []
        for item in all_items:
            sid = str(item.get("subjectId", "") or "")
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                unique_items.append(item)

        # Filter by type
        if type == "movie":
            unique_items = [
                item for item in unique_items
                if not ((item.get("seNum", 0) or 0) > 0 or item.get("subjectType", 0) == 2)
            ]
        elif type == "series":
            unique_items = [
                item for item in unique_items
                if (item.get("seNum", 0) or 0) > 0 or item.get("subjectType", 0) == 2
            ]

        results = [format_search_item(item) for item in unique_items]

        # Sort
        if sort == "rating":
            results.sort(key=lambda x: x.get("rating", 0) or 0, reverse=True)
        elif sort == "newest":
            results.sort(key=lambda x: x.get("year", "") or "", reverse=True)
        else:  # random
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
        logger.error(f"❌ Adult content error: {type(e).__name__}: {str(e)[:100]}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب المحتوى.",
        )


@router.get("/adult_keywords")
async def adult_keywords():
    """إرجاع جميع الكلمات المفتاحية المتاحة لقسم +18."""
    return JSONResponse(content={
        "status": "success",
        "keywords": ADULT_QUERIES,
        "total": len(ADULT_QUERIES),
    })
