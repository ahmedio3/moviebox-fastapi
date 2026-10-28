"""MovieBox HTTP client session management with automatic token caching and refreshing."""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager

from moviebox_api.v3.core import Homepage
from moviebox_api.v3.http_client import MovieBoxHttpClient

logger = logging.getLogger(__name__)

# ─── Android client identity (v4.0.02 parity) ───────────────────────────────
# The MovieBox backend serves a fake "update your app" clip to outdated
# clients. Present the current app identity on every signed request.
APP_VERSION_NAME = "4.0.02"
APP_VERSION_CODE = 50020126
CLIENT_USER_AGENT = (
    f"com.community.oneroom/{APP_VERSION_CODE} "
    "(Linux; U; Android 13; en_US; 2201117TY; "
    "Build/TQ2A.230405.003; Cronet/135.0.7012.3)"
)
CLIENT_INFO = json.dumps(
    {
        "package_name": "com.community.oneroom",
        "version_name": APP_VERSION_NAME,
        "version_code": APP_VERSION_CODE,
        "os": "android",
        "os_version": "13",
        "install_ch": "ps",
        "device_id": uuid.uuid4().hex,
        "install_store": "ps",
        "gaid": str(uuid.uuid4()),
        "brand": "Redmi",
        "model": "2201117TY",
        "system_language": "en",
        "net": "NETWORK_WIFI",
        "region": "US",
        "timezone": "Asia/Kolkata",
        "sp_code": "40401",
        "X-Play-Mode": "2",
    },
    separators=(",", ":"),
)

_cached_token: str | None = None
_token_lock = asyncio.Lock()


class ModernMovieBoxHttpClient(MovieBoxHttpClient):
    """MovieBox client that identifies as the current Android app build."""

    def _signed_headers(
        self,
        method: str,
        url: str,
        accept: str = "application/json",
        content_type: str = "application/json",
        body: str | None = None,
        include_play_mode: bool = False,
    ) -> dict[str, str]:
        headers = super()._signed_headers(
            method,
            url,
            accept=accept,
            content_type=content_type,
            body=body,
            include_play_mode=include_play_mode,
        )
        headers["User-Agent"] = CLIENT_USER_AGENT
        headers["X-Client-Info"] = CLIENT_INFO
        headers["X-M-Version"] = APP_VERSION_NAME
        return headers


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
    async with ModernMovieBoxHttpClient() as client:
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
