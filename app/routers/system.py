"""System health and API documentation index endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["System"])


@router.get("/health")
async def health_check():
    return JSONResponse(content={"status": "healthy", "service": "watchera-moviebox"})


@router.get("/")
async def root():
    return JSONResponse(content={
        "name": "MovieBox FastAPI Backend for Watchera",
        "version": "8.2.1",
        "endpoints": {
            "search":                  "/search?query=TITLE&original_language=en&limit=8",
            "search_v2":               "/search_v2?query=TITLE&tab=all&page=1&limit=15",
            "suggest":                 "/suggest?query=avat&limit=10",
            "recommend":               "/recommend?subject_id=ID&page=1&limit=10",
            "home":                    "/home?page=1&safe_mode=true&limit_per_section=20",
            "popular_searches":        "/popular_searches?limit=10",
            "get_download_links":      "/get_download_links?subject_id=ID&season=1&episode=1&page=1&limit=10",
            "get_download_links_1res": "/get_download_links?subject_id=ID&resolution=1080",
            "get_stream":              "/get_stream?subject_id=ID&season=0&episode=0",
            "get_subtitles":           "/get_subtitles?subject_id=ID&resource_id=RID",
            "trending":                "/trending?tab=movie&page=1&safe_mode=true&limit=20",
            "browse":                  "/browse?genre=action,drama&type=all&sort=rating&safe_mode=true&limit=20",
            "random":                  "/random?type=all&safe_mode=true&limit=1",
            "item_details":            "/item_details?subject_id=ID&include_seasons=true",
            "adult":                   "/adult?type=all&queries=hentai,xxx&limit=10",
            "adult_keywords":          "/adult_keywords",
            "health":                  "/health",
        },
        "rate_limits": {
            "search": "30/minute",
            "search_v2": "30/minute",
            "suggest": "60/minute",
            "recommend": "30/minute",
            "home": "15/minute",
            "popular_searches": "30/minute",
            "get_download_links": "30/minute",
            "get_stream": "30/minute",
            "get_subtitles": "60/minute",
            "trending": "15/minute",
            "browse": "15/minute",
            "random": "15/minute",
            "item_details": "30/minute",
            "adult": "10/minute",
        },
    })
