"""FastAPI route handlers organized by feature domain."""

from app.routers.search import router as search_router
from app.routers.media import router as media_router
from app.routers.discover import router as discover_router
from app.routers.adult import router as adult_router
from app.routers.system import router as system_router

__all__ = [
    "search_router",
    "media_router",
    "discover_router",
    "adult_router",
    "system_router",
]
