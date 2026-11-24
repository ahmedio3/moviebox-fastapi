"""MovieBox web API helpers for suggestions, recommendations, and popular searches.

The v1 wrappers in ``moviebox_api`` still point at the retired
``/wefeed-h5-bff/web/...`` routes on the API host. The same features are
available on the current ``/wefeed-h5api-bff/...`` routes, so these helpers
call them directly with the web client headers.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

WEB_API_BASE = "https://h5-api.aoneroom.com"
WEB_API_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:137.0) "
        "Gecko/20100101 Firefox/137.0"
    ),
    "Referer": "https://videodownloader.site/",
    "X-Client-Info": '{"timezone":"Africa/Nairobi"}',
}

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _unwrap(payload: dict) -> dict:
    """Return the ``data`` object, tolerating endpoints without an envelope."""
    if not isinstance(payload, dict):
        return {}
    code = payload.get("code")
    if code not in (None, 0):
        raise RuntimeError(
            f"MovieBox web API error {code}: {payload.get('message', '')}"
        )
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


async def _get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(
        headers=WEB_API_HEADERS,
        timeout=_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = await client.get(f"{WEB_API_BASE}{path}", params=params)
        response.raise_for_status()
        return _unwrap(response.json())


async def _post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(
        headers=WEB_API_HEADERS,
        timeout=_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = await client.post(f"{WEB_API_BASE}{path}", json=body)
        response.raise_for_status()
        return _unwrap(response.json())


async def fetch_suggestions(query: str, limit: int = 10) -> dict:
    """Autocomplete titles for a partially typed query."""
    return await _post(
        "/wefeed-h5api-bff/subject/search-suggest",
        {"per_page": limit, "keyword": query},
    )


async def fetch_recommendations(
    subject_id: str, page: int = 1, limit: int = 10
) -> dict:
    """Titles similar to the given subject."""
    return await _get(
        "/wefeed-h5api-bff/subject/detail-rec",
        {"subjectId": subject_id, "page": page, "perPage": limit},
    )


async def fetch_popular_searches() -> dict:
    """Titles many people search for, plus hot Movie/TV lists."""
    return await _get("/wefeed-h5api-bff/subject/everyone-search")
