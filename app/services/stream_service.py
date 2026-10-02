"""Streaming service for resolving real MPEG-DASH manifests and signed cookies."""

import base64
import logging

from moviebox_api.v3.http_client import MovieBoxHttpClient
from moviebox_api.v3.urls import PLAY_INFO_PATH

logger = logging.getLogger(__name__)


def extract_dash_from_cookie(sign_cookie: str) -> tuple[str | None, str | None]:
    """
    Extracts the DASH manifest URL (index.mpd) and the Edge-Cache-Cookie header value.
    """
    if not sign_cookie or "urlprefix=" not in sign_cookie:
        return None, None
    try:
        prefix_b64 = sign_cookie.split("urlprefix=")[1].split(":")[0]
        padding = (4 - len(prefix_b64) % 4) % 4
        prefix = base64.b64decode(prefix_b64 + "=" * padding).decode("utf-8")
        if not prefix.endswith("/"):
            prefix += "/"
        manifest_url = f"{prefix}index.mpd"
        return manifest_url, sign_cookie.strip()
    except Exception as e:
        logger.error(f"Error parsing sign_cookie: {e}")
        return None, None


async def resolve_stream_for_episode(
    client: MovieBoxHttpClient, subject_id: str, season: int = 0, episode: int = 0
) -> dict | None:
    """
    Queries /wefeed-mobile-bff/subject-api/play-info and extracts the real DASH stream and signed cookie.
    """
    try:
        data = await client.get_from_api(
            PLAY_INFO_PATH,
            params={"subjectId": subject_id, "se": season, "ep": episode},
            include_play_mode=True,
        )
        streams = data.get("streams", []) or []
        for st in streams:
            sign_cookie = st.get("signCookie", "")
            manifest_url, cookie_val = extract_dash_from_cookie(sign_cookie)
            if manifest_url:
                resolutions = [
                    int(r.strip())
                    for r in st.get("resolutions", "").split(",")
                    if r.strip().isdigit()
                ]
                return {
                    "manifest_url": manifest_url,
                    "cookie": cookie_val,
                    "headers": {
                        "Cookie": cookie_val,
                        "User-Agent": "Mozilla/5.0",
                    },
                    "resolutions": resolutions,
                    "codec": st.get("codecName"),
                    "duration": int(st.get("duration", 0) or 0),
                    "size": int(st.get("size", 0) or 0),
                }
    except Exception as e:
        logger.warning(
            f"⚠️ Failed to resolve play-info for {subject_id} S{season}E{episode}: {e}"
        )
    return None
