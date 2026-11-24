"""Extra search and discovery features backed by MovieBox web APIs."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from moviebox_api.v3.constants import TabID
from moviebox_api.v3.core import Homepage, SearchV2

from app.core.client import get_client
from app.core.limiter import limiter
from app.services.extra_service import (
    fetch_popular_searches,
    fetch_recommendations,
    fetch_suggestions,
)
from app.utils.formatters import format_search_item
from app.utils.helpers import is_adult

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Features"])

TAB_MAP = {
    "all": TabID.ALL,
    "movie": TabID.MOVIE,
    "tv": TabID.TV_SERIES,
    "series": TabID.TV_SERIES,
    "short_tv": TabID.SHORT_TV,
    "shorttv": TabID.SHORT_TV,
    "movie_tv": TabID.MOVIE_TV,
    "movietv": TabID.MOVIE_TV,
    "fightzone": TabID.FIGHTZONE,
    "sports": TabID.SPORTS,
    "music": TabID.MUSIC,
    "people": TabID.PEOPLE,
    "education": TabID.EDUCATION,
}


def _dedupe(items: list[dict]) -> list[dict]:
    """Remove duplicate subjects while preserving order."""
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        subject_id = str(item.get("subjectId") or "")
        if subject_id and subject_id in seen:
            continue
        if subject_id:
            seen.add(subject_id)
        unique.append(item)
    return unique


def _format_items(
    items: list[dict],
    safe_mode: bool = True,
    limit: int | None = None,
) -> list[dict]:
    """Format raw subjects and optionally drop adult content."""
    formatted: list[dict] = []
    for item in _dedupe(items):
        if not item.get("subjectId"):
            continue
        if safe_mode and is_adult(item):
            continue
        formatted.append(format_search_item(item))
    if limit is not None:
        formatted = formatted[:limit]
    return formatted


def _section_groups(section: dict) -> list[tuple[str, list[dict]]]:
    """Return ``(title, subjects)`` groups for a homepage section."""
    groups: list[tuple[str, list[dict]]] = []

    direct = list(section.get("subjects") or [])
    direct.extend(section.get("verticalStyleSubjects") or [])
    if direct:
        groups.append((section.get("title", ""), direct))

    ranking_list = section.get("rankingListData") or {}
    for group in ranking_list.get("items") or []:
        subjects = list(group.get("subjects") or [])
        if subjects:
            groups.append((group.get("title", ""), subjects))

    ranking = section.get("rankingData") or {}
    if isinstance(ranking, dict) and ranking.get("subjects"):
        groups.append((ranking.get("title", ""), ranking["subjects"]))

    banner = section.get("banner") or {}
    banner_subjects = [
        entry["subject"]
        for entry in (banner.get("banners") or [])
        if entry.get("subject")
    ]
    if banner_subjects:
        groups.append((section.get("title", ""), banner_subjects))

    return groups


@router.get("/suggest")
@limiter.limit("60/minute")
async def suggest_titles(
    request: Request,
    query: str = Query(..., description="النص المكتوب في شريط البحث"),
    limit: int = Query(10, ge=1, le=20, description="عدد الاقتراحات"),
):
    """إكمال تلقائي لعناوين MovieBox أثناء الكتابة."""
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query لا يمكن أن يكون فارغاً")

    try:
        data = await fetch_suggestions(query, limit)
        suggestions = [
            {"text": item.get("word", ""), "type": item.get("type", 0)}
            for item in (data.get("items") or [])
            if item.get("word")
        ][:limit]

        return JSONResponse(content={
            "status": "success",
            "query": query,
            "total_results": len(suggestions),
            "suggestions": suggestions,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Suggest error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب الاقتراحات.",
        )


@router.get("/recommend")
@limiter.limit("30/minute")
async def recommend_titles(
    request: Request,
    subject_id: str = Query(..., description="معرّف المحتوى المرجعي"),
    page: int = Query(1, ge=1, description="رقم الصفحة"),
    limit: int = Query(10, ge=1, le=50, description="عدد النتائج"),
    safe_mode: bool = Query(True, description="تصفية المحتوى غير اللائق"),
):
    """عروض مشابهة للمحتوى الحالي."""
    subject_id = subject_id.strip()
    if not subject_id:
        raise HTTPException(status_code=400, detail="subject_id لا يمكن أن يكون فارغاً")

    try:
        data = await fetch_recommendations(subject_id, page, limit)
        raw_items = _dedupe(data.get("items") or [])
        results = _format_items(raw_items, safe_mode, limit)

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "page": page,
            "limit": limit,
            "total_results": len(results),
            "has_more": len(raw_items) >= limit,
            "results": results,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Recommend error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب العروض المشابهة.",
        )


@router.get("/popular_searches")
@limiter.limit("30/minute")
async def popular_searches(
    request: Request,
    limit: int = Query(10, ge=1, le=20, description="عدد العناصر لكل فئة"),
    safe_mode: bool = Query(True, description="تصفية المحتوى غير اللائق"),
):
    """العناوين الأكثر بحثاً وقوائم Movie/TV الرائجة."""
    try:
        data = await fetch_popular_searches()

        everyone_search = [
            item.get("title", "")
            for item in (data.get("everyoneSearch") or [])
            if item.get("title")
        ]

        hot: list[dict] = []
        for category in data.get("hot") or []:
            results = _format_items(
                category.get("items") or [],
                safe_mode,
                limit,
            )
            if not results:
                continue
            hot.append({
                "category": category.get("category", ""),
                "name": category.get("name", ""),
                "total_results": len(results),
                "results": results,
            })

        return JSONResponse(content={
            "status": "success",
            "everyone_search": everyone_search,
            "hot": hot,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Popular searches error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب عمليات البحث الشائعة.",
        )


@router.get("/home")
@limiter.limit("15/minute")
async def home_sections(
    request: Request,
    page: int = Query(1, ge=1, description="رقم الصفحة"),
    safe_mode: bool = Query(True, description="تصفية المحتوى غير اللائق"),
    limit_per_section: int = Query(
        20, ge=1, le=50, description="أقصى عدد عناصر في كل قسم"
    ),
):
    """أقسام الصفحة الرئيسية بعناوينها وترتيبها الأصلي."""
    try:
        async with get_client() as client:
            homepage = Homepage(client_session=client)
            homepage._page_number = page
            homepage._tab_id = 0
            data = await homepage.get_content()

        sections: list[dict] = []
        for section in data.get("items") or []:
            groups: list[dict] = []
            direct_items: list[dict] = []

            for group_title, subjects in _section_groups(section):
                items = _format_items(subjects, safe_mode, limit_per_section)
                if not items:
                    continue
                if group_title == section.get("title", ""):
                    direct_items.extend(items)
                else:
                    groups.append({
                        "title": group_title,
                        "total_results": len(items),
                        "results": items,
                    })

            # Flatten groups into the section's main item list as well.
            flattened = list(direct_items)
            for group in groups:
                flattened.extend(group["results"])

            unique_items: list[dict] = []
            seen: set[str] = set()
            for item in flattened:
                subject_id = item.get("subject_id")
                if subject_id in seen:
                    continue
                seen.add(subject_id)
                unique_items.append(item)

            if not unique_items and not groups:
                continue

            entry = {
                "title": section.get("title", ""),
                "type": section.get("type", ""),
                "total_results": len(unique_items),
                "items": unique_items[:limit_per_section],
            }
            if groups:
                entry["groups"] = groups
            sections.append(entry)

        return JSONResponse(content={
            "status": "success",
            "page": page,
            "total_sections": len(sections),
            "sections": sections,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Home error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب أقسام الصفحة الرئيسية.",
        )


@router.get("/search_v2")
@limiter.limit("30/minute")
async def search_v2(
    request: Request,
    query: str = Query(..., description="اسم الفيلم أو المسلسل"),
    tab: str = Query(
        "all",
        description=(
            "all | movie | tv | short_tv | movie_tv | "
            "fightzone | sports | music | people | education"
        ),
    ),
    page: int = Query(1, ge=1, description="رقم الصفحة"),
    limit: int = Query(15, ge=1, le=20, description="عدد النتائج لكل مجموعة"),
    safe_mode: bool = Query(True, description="تصفية المحتوى غير اللائق"),
):
    """بحث متقدم بتبويبات ومجموعات نتائج."""
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query لا يمكن أن يكون فارغاً")

    tab_key = tab.strip().lower()
    tab_id = TAB_MAP.get(tab_key)
    if tab_id is None:
        raise HTTPException(
            status_code=400,
            detail="tab يجب أن يكون: all, movie, tv, short_tv, movie_tv, fightzone, sports, music, people, education",
        )

    try:
        async with get_client() as client:
            searcher = SearchV2(
                client_session=client,
                query=query,
                tab_id=tab_id,
                page=page,
                per_page=limit,
            )
            data = await searcher.get_content()

        main = data.get("items") or {}
        main_items = _format_items(
            main.get("subjects") or [],
            safe_mode,
            limit,
        )

        groups: list[dict] = []
        for group in data.get("results") or []:
            if not group.get("title"):
                # The first result group mirrors ``items`` (the main results).
                continue
            results = _format_items(
                group.get("subjects") or [],
                safe_mode,
                limit,
            )
            if not results:
                continue
            groups.append({
                "title": group.get("title", ""),
                "topic_type": group.get("topicType", ""),
                "show_more": bool(group.get("showMore")),
                "more_tab_id": group.get("moreTabId") or "",
                "total_results": len(results),
                "results": results,
            })

        flattened: list[dict] = []
        seen: set[str] = set()
        for item in main_items + [i for group in groups for i in group["results"]]:
            subject_id = item.get("subject_id")
            if subject_id in seen:
                continue
            seen.add(subject_id)
            flattened.append(item)

        tabs: list[dict] = []
        for item in data.get("tabs") or []:
            tabs.append({"id": item.get("tabId"), "name": item.get("name")})
            for sub in item.get("subs") or []:
                if (
                    sub.get("tabId") == item.get("tabId")
                    and (sub.get("name") or "").lower() == "all"
                ):
                    continue
                tabs.append({
                    "id": sub.get("tabId"),
                    "name": sub.get("name"),
                    "parent_id": item.get("tabId"),
                })

        return JSONResponse(content={
            "status": "success",
            "query": query,
            "tab": tab_id.value,
            "page": page,
            "limit": limit,
            "total_results": len(flattened),
            "tabs": tabs,
            "main": {
                "topic_type": main.get("topicType", ""),
                "total_results": len(main_items),
                "results": main_items,
            },
            "groups": groups,
            "results": flattened,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Search v2 error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في البحث المتقدم.",
        )
