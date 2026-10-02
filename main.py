"""
تطبيق FastAPI للحصول على روابط التحميل والبحث والترجمة من مكتبة moviebox-api v3

Modular entrypoint compatible with Vercel and Watchera Android client.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from moviebox_api.v3.http_client import MovieBoxHttpClient
from slowapi.errors import RateLimitExceeded

from app.config import (
    ALL_RESOLUTIONS,
    PER_PAGE_OPTIONS,
    TMDB_LANG_MAP,
    DUBBED_KEYWORDS,
    ARABIC_LAN_CODES,
    DUMMY_VIDEO_HASH,
    ADULT_KEYWORDS,
    ADULT_QUERIES,
)
from app.core.client import _refresh_token, get_client
from app.core.limiter import limiter, rate_limit_handler
from app.routers import (
    adult_router,
    discover_router,
    media_router,
    search_router,
    system_router,
)
from app.utils.formatters import (
    build_subtitle_summary,
    format_caption,
    format_download_item,
    format_search_item,
    score_result,
)
from app.utils.helpers import (
    get_cover_url,
    is_adult,
    is_arabic_caption,
    is_dubbed,
    is_dummy_video,
    parse_languages,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Watchera MovieBox API started")
    try:
        async with MovieBoxHttpClient() as client:
            await _refresh_token(client)
    except Exception as e:
        logger.warning(f"⚠️ Startup token initialization skipped: {e}")
    yield
    logger.info("🛑 Shutting down")


# ─── FastAPI Application ─────────────────────────────────────────────────────

app = FastAPI(
    title="MovieBox FastAPI Backend for Watchera",
    version="8.1",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# ─── Rate Limiter State & Exception Handling ─────────────────────────────────

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# ─── Register Domain Routers ─────────────────────────────────────────────────

app.include_router(search_router)
app.include_router(media_router)
app.include_router(discover_router)
app.include_router(adult_router)
app.include_router(system_router)


# ─── CLI Entrypoint ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import sys
    import uvicorn

    port = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--port" and i < len(sys.argv):
            port = int(sys.argv[i + 1])
            break
        elif arg.isdigit():
            port = int(arg)
            break

    if not port:
        port = int(
            os.environ.get("SERVER_PORT")
            or os.environ.get("PORT")
            or os.environ.get("P_SERVER_PORT")
            or 10622
        )

    uvicorn.run("main:app", host="0.0.0.0", port=port)
