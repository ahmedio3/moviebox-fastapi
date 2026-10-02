"""MovieBox HTTP client session management with automatic token caching and refreshing."""

import asyncio
import logging
from contextlib import asynccontextmanager

from moviebox_api.v3.core import Homepage
from moviebox_api.v3.http_client import MovieBoxHttpClient

logger = logging.getLogger(__name__)

_cached_token: str | None = None
_token_lock = asyncio.Lock()


async def _refresh_token(client: MovieBoxHttpClient) -> str | None:
    global _cached_token
    try:
        hp = Homepage(client_session=client)
        await hp.get_content()
        if client._runtime_token:
            _cached_token = client._runtime_token
            logger.info("🔑 Fresh MovieBox auth token acquired")
            return _cached_token
    except Exception as e:
        logger.warning(f"⚠️ Failed to acquire MovieBox auth token: {e}")
    return None


@asynccontextmanager
async def get_client():
    global _cached_token
    async with MovieBoxHttpClient() as client:
        if _cached_token:
            client._runtime_token = _cached_token
        else:
            async with _token_lock:
                if not _cached_token:
                    await _refresh_token(client)
                else:
                    client._runtime_token = _cached_token

        yield client

        if client._runtime_token and client._runtime_token != _cached_token:
            _cached_token = client._runtime_token
