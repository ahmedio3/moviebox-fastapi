"""Streaming service for resolving real MPEG-DASH manifests and signed cookies."""

import base64
import logging
import re

from moviebox_api.v3.http_client import MovieBoxHttpClient
from moviebox_api.v3.urls import PLAY_INFO_PATH, SUBJECT_GET_PATH

from app.utils.helpers import is_dummy_video

logger = logging.getLogger(__name__)

# The native play-info endpoint now returns an anti-piracy warning clip for
# unverified clients. The web player endpoint still resolves the real media
# (DASH + Edge-Cache-Cookie), so it is used as a fallback.
WEB_PLAY_PATH = "/wefeed-h5api-bff/subject/play"
WEB_API_BASES = (
    "https://h5-api.aoneroom.com",
    "https://movie-box.co",
)
WEB_REFERER_BASE = "https://movie-box.co"
WEB_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0.0.0 Mobile Safari/537.36"
)

_detail_path_cache: dict[str, str] = {}
_MAX_DETAIL_PATH_CACHE = 256


async def _get_detail_path(
    client: MovieBoxHttpClient, subject_id: str
) -> str | None:
    """Returns the slug used by the web player (from ``detailUrl``)."""
    cached = _detail_path_cache.get(subject_id)
    if cached:
        return cached

    try:
        details = await client.get_from_api(
            SUBJECT_GET_PATH, params={"subjectId": subject_id}
        )
        detail_url = str(
            details.get("detailUrl") or details.get("detail_url") or ""
        )
        detail_path = detail_url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        if detail_path:
            if len(_detail_path_cache) >= _MAX_DETAIL_PATH_CACHE:
                _detail_path_cache.clear()
            _detail_path_cache[subject_id] = detail_path
            return detail_path
    except Exception as e:
        logger.warning(
            f"⚠️ Failed to resolve detailPath for {subject_id}: {e}"
        )
    return None


async def _fetch_web_play(
    client: MovieBoxHttpClient,
    subject_id: str,
    season: int,
    episode: int,
    detail_path: str,
) -> dict | None:
    """Calls the web player endpoint and returns its ``data`` payload."""
    params = {
        "subjectId": subject_id,
        "se": season,
        "ep": episode,
        "detailPath": detail_path,
        "streamSignType": 1,
        "supportCodecs[hevc]": 1,
        "supportCodecs[h264]": 1,
    }
    referer = (
        f"{WEB_REFERER_BASE}/movies/{detail_path}"
        f"?id={subject_id}&type=/movie/detail"
        f"&detailSe={season}&detailEp={episode}&lang=en"
    )
    headers = {
        "User-Agent": WEB_USER_AGENT,
        "Referer": referer,
        "Accept": "application/json",
    }

    for base in WEB_API_BASES:
        try:
            response = await client.get_raw(
                f"{base}{WEB_PLAY_PATH}", params=params, headers=headers
            )
            if response.status_code != 200:
                logger.debug(
                    f"Web play {base} returned HTTP {response.status_code}"
                )
                continue
            data = response.json().get("data") or {}
            if data.get("streams") or data.get("dash") or data.get("hls"):
                return data
        except Exception as e:
            logger.debug(f"Web play {base} failed: {type(e).__name__}: {e}")
    return None


async def _mpd_sizes(
    client: MovieBoxHttpClient,
    manifest_url: str,
    cookie: str | None,
    fallback_duration: int,
) -> dict[int, int]:
    headers = {"User-Agent": WEB_USER_AGENT}
    if cookie:
        headers["Cookie"] = cookie
    try:
        mpd_resp = await client.get_raw(manifest_url, headers=headers)
        if mpd_resp.status_code == 200:
            return parse_mpd_content(
                mpd_resp.text, fallback_duration=fallback_duration
            )
    except Exception as e:
        logger.warning(f"⚠️ Failed to fetch/parse web MPD sizes: {e}")
    return {}


def _build_web_stream_info(
    data: dict, sizes: dict[int, int]
) -> dict | None:
    """Converts a web ``subject/play`` payload into the internal stream shape."""
    for st in data.get("dash") or []:
        sign_cookie = str(st.get("signCookie") or "")
        manifest_url, cookie_val = extract_dash_from_cookie(sign_cookie)
        if not manifest_url:
            candidate = str(st.get("url") or "")
            if candidate and ".mpd" in candidate:
                manifest_url = candidate
                cookie_val = sign_cookie.strip() or None
        if not manifest_url or is_dummy_video(manifest_url):
            continue

        resolutions = [
            int(r.strip())
            for r in str(st.get("resolutions") or "").split(",")
            if r.strip().isdigit()
        ]
        base_size = int(st.get("size", 0) or 0)
        duration = int(st.get("duration", 0) or 0)
        if not sizes and base_size > 0:
            sizes = estimate_sizes_by_resolution(base_size, resolutions)

        return {
            "manifest_url": manifest_url,
            "urls_by_resolution": {r: manifest_url for r in resolutions},
            "cookie": cookie_val or "",
            "headers": {
                "Cookie": cookie_val or "",
                "User-Agent": WEB_USER_AGENT,
            },
            "resolutions": resolutions,
            "sizes": sizes,
            "codec": st.get("codecName"),
            "duration": duration,
            "size": base_size,
            "stream_type": "dash",
        }

    # Some titles only expose progressive MP4 mirrors on the web endpoint.
    variants: dict[int, dict] = {}
    for st in data.get("streams") or []:
        url = str(st.get("url") or "")
        if not url or is_dummy_video(url):
            continue
        res_values = [
            int(r.strip())
            for r in str(st.get("resolutions") or "").split(",")
            if r.strip().isdigit()
        ]
        resolution = res_values[0] if res_values else 0
        variants[resolution] = st

    if not variants:
        return None

    resolutions = sorted((r for r in variants if r > 0), reverse=True)
    best_resolution = resolutions[0] if resolutions else 0
    best = variants[best_resolution]
    return {
        "manifest_url": best.get("url"),
        "urls_by_resolution": {
            r: st.get("url") for r, st in variants.items()
        },
        "cookie": "",
        "headers": {"User-Agent": WEB_USER_AGENT},
        "resolutions": resolutions,
        "sizes": {
            r: int(st.get("size", 0) or 0) for r, st in variants.items()
        },
        "codec": best.get("codecName"),
        "duration": int(best.get("duration", 0) or 0),
        "size": int(best.get("size", 0) or 0),
        "stream_type": "mp4",
    }


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
    Resolves the real media stream for a movie/episode.

    Tries the native ``play-info`` endpoint first. When MovieBox answers with
    the anti-piracy warning clip (no usable ``signCookie``), the web player
    endpoint is used to recover the real DASH manifest and Edge-Cache-Cookie.
    """
    native_error: Exception | None = None
    try:
        data = await client.get_from_api(
            PLAY_INFO_PATH,
            params={"subjectId": subject_id, "se": season, "ep": episode},
            include_play_mode=True,
        )
        streams = data.get("streams", []) or []
        for st in streams:
            sign_cookie = st.get("signCookie", "") or ""
            manifest_url, cookie_val = extract_dash_from_cookie(sign_cookie)
            if not manifest_url or is_dummy_video(manifest_url):
                continue

            resolutions = [
                int(r.strip())
                for r in str(st.get("resolutions", "")).split(",")
                if r.strip().isdigit()
            ]

            sizes: dict[int, int] = {}
            base_size = int(st.get("size", 0) or 0)
            if fetch_mpd:
                try:
                    mpd_headers = {"User-Agent": "Mozilla/5.0"}
                    if cookie_val:
                        mpd_headers["Cookie"] = cookie_val
                    mpd_resp = await client.get_raw(
                        manifest_url, headers=mpd_headers
                    )
                    if mpd_resp.status_code == 200:
                        sizes = parse_mpd_content(
                            mpd_resp.text,
                            fallback_duration=int(st.get("duration", 0) or 0),
                        )
                except Exception as ex:
                    logger.warning(
                        f"⚠️ Failed to fetch/parse MPD for sizes: {ex}"
                    )

            if not sizes and base_size > 0:
                sizes = estimate_sizes_by_resolution(base_size, resolutions)

            return {
                "manifest_url": manifest_url,
                "urls_by_resolution": {r: manifest_url for r in resolutions},
                "cookie": cookie_val,
                "headers": {
                    "Cookie": cookie_val or "",
                    "User-Agent": "Mozilla/5.0",
                },
                "resolutions": resolutions,
                "sizes": sizes,
                "codec": st.get("codecName"),
                "duration": int(st.get("duration", 0) or 0),
                "size": base_size,
                "stream_type": "dash",
            }
    except Exception as e:
        native_error = e
        logger.warning(
            f"⚠️ Native play-info failed for {subject_id} S{season}E{episode}: {e}"
        )

    detail_path = await _get_detail_path(client, subject_id)
    if detail_path:
        web_data = await _fetch_web_play(
            client, subject_id, season, episode, detail_path
        )
        if web_data:
            sizes: dict[int, int] = {}
            if fetch_mpd:
                for st in web_data.get("dash") or []:
                    sign_cookie = str(st.get("signCookie") or "")
                    candidate, cookie_val = extract_dash_from_cookie(sign_cookie)
                    if not candidate or is_dummy_video(candidate):
                        continue
                    sizes = await _mpd_sizes(
                        client,
                        candidate,
                        cookie_val,
                        int(st.get("duration", 0) or 0),
                    )
                    break

            info = _build_web_stream_info(web_data, sizes)
            if info:
                logger.info(
                    f"🌐 Resolved {subject_id} S{season}E{episode} via web play fallback"
                )
                return info

    if native_error:
        logger.warning(
            f"⚠️ Could not resolve stream for {subject_id} S{season}E{episode}"
        )
    return None
