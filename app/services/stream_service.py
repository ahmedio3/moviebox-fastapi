"""Streaming service for resolving real MPEG-DASH manifests and signed cookies."""

import base64
import logging

from moviebox_api.v3.http_client import MovieBoxHttpClient
from moviebox_api.v3.urls import PLAY_INFO_PATH

import re

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


def parse_mpd_content(mpd_text: str, fallback_duration: int = 0) -> dict[int, int]:
    """
    Extracts representation bandwidth and calculates accurate total bytes for each video height.
    Formula: ((video_bandwidth + audio_bandwidth) * duration_seconds) / 8
    """
    total_seconds = 0.0
    dur_match = re.search(r'mediaPresentationDuration="([^"]+)"', mpd_text)
    if dur_match:
        dur_str = dur_match.group(1)
        h_match = re.search(r'(\d+)H', dur_str)
        m_match = re.search(r'(\d+)M', dur_str)
        s_match = re.search(r'([\d.]+)S', dur_str)
        h = float(h_match.group(1)) if h_match else 0.0
        m = float(m_match.group(1)) if m_match else 0.0
        s = float(s_match.group(1)) if s_match else 0.0
        total_seconds = h * 3600 + m * 60 + s

    if total_seconds <= 0 and fallback_duration > 0:
        total_seconds = float(fallback_duration)

    if total_seconds <= 0:
        return {}

    audio_bw = 128000
    video_reps: list[tuple[int, int]] = []
    for match in re.finditer(r'<Representation\s+([^>]+)>', mpd_text, re.IGNORECASE):
        attrs = match.group(1)
        mime_match = re.search(r'mimeType="([^"]+)"', attrs)
        mime_str = mime_match.group(1) if mime_match else ""
        height_match = re.search(r'height="(\d+)"', attrs)
        height = int(height_match.group(1)) if height_match else 0
        bw_match = re.search(r'bandwidth="(\d+)"', attrs)
        bw = int(bw_match.group(1)) if bw_match else 0

        if mime_str.startswith("audio") or height == 0:
            if bw > 0:
                audio_bw = bw
        elif height > 0 and bw > 0:
            video_reps.append((height, bw))

    sizes: dict[int, int] = {}
    for height, bw in video_reps:
        sizes[height] = int(((bw + audio_bw) * total_seconds) / 8.0)
    return sizes


def estimate_sizes_by_resolution(base_size: int, resolutions: list[int]) -> dict[int, int]:
    """Generates realistic proportional sizes if MPD bandwidth parsing is unavailable."""
    if base_size <= 0:
        return {}
    ratios = {
        1080: 1.0,
        720: 0.54,
        480: 0.28,
        360: 0.16
    }
    result = {}
    for r in resolutions:
        ratio = ratios.get(r, 0.5)
        result[r] = int(base_size * ratio)
    return result


async def resolve_stream_for_episode(
    client: MovieBoxHttpClient,
    subject_id: str,
    season: int = 0,
    episode: int = 0,
    fetch_mpd: bool = True,
) -> dict | None:
    """
    Queries /wefeed-mobile-bff/subject-api/play-info and extracts the real DASH stream,
    signed cookie, and accurate sizes for each resolution.
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

                sizes: dict[int, int] = {}
                base_size = int(st.get("size", 0) or 0)
                if fetch_mpd:
                    try:
                        mpd_resp = await client.get_raw(
                            manifest_url,
                            headers={"Cookie": cookie_val, "User-Agent": "Mozilla/5.0"}
                        )
                        if mpd_resp.status_code == 200:
                            sizes = parse_mpd_content(
                                mpd_resp.text,
                                fallback_duration=int(st.get("duration", 0) or 0)
                            )
                    except Exception as ex:
                        logger.warning(f"⚠️ Failed to fetch/parse MPD for sizes: {ex}")

                if not sizes and base_size > 0:
                    sizes = estimate_sizes_by_resolution(base_size, resolutions)

                return {
                    "manifest_url": manifest_url,
                    "cookie": cookie_val,
                    "headers": {
                        "Cookie": cookie_val,
                        "User-Agent": "Mozilla/5.0",
                    },
                    "resolutions": resolutions,
                    "sizes": sizes,
                    "codec": st.get("codecName"),
                    "duration": int(st.get("duration", 0) or 0),
                    "size": base_size,
                }
    except Exception as e:
        logger.warning(
            f"⚠️ Failed to resolve play-info for {subject_id} S{season}E{episode}: {e}"
        )
    return None
