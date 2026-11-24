"""Homepage feed helpers with regional fallback.

MovieBox's mixed home feed (tab 0) can come back empty in some regions even
though the movie/TV/anime tabs still return content. When that happens,
compose the feed from the individual tabs instead of returning an empty page.
"""

import asyncio

from moviebox_api.v3.core import Homepage
from moviebox_api.v3.http_client import MovieBoxHttpClient

FALLBACK_TABS = (2, 5, 8)


async def _fetch_tab(
    client: MovieBoxHttpClient, tab_id: int, page: int
) -> list[dict]:
    homepage = Homepage(client_session=client)
    homepage._page_number = page
    homepage._tab_id = tab_id
    data = await homepage.get_content()
    return list(data.get("items") or [])


async def fetch_home_sections(
    client: MovieBoxHttpClient, page: int = 1, tab_id: int = 0
) -> list[dict]:
    """Return homepage sections, composing them from tabs when tab 0 is empty."""
    sections = await _fetch_tab(client, tab_id, page)
    if any(section.get("subjects") for section in sections):
        return sections
    if tab_id != 0:
        return sections

    results = await asyncio.gather(
        *(_fetch_tab(client, fallback, page) for fallback in FALLBACK_TABS),
        return_exceptions=True,
    )

    merged: list[dict] = []
    seen_titles: set[str] = set()
    for result in results:
        if isinstance(result, Exception):
            continue
        for section in result:
            if not section.get("subjects"):
                continue
            title = section.get("title") or ""
            if title and title in seen_titles:
                continue
            seen_titles.add(title)
            merged.append(section)
    return merged
