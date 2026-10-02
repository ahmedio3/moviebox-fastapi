"""Media endpoints for download links, MPEG-DASH streaming, and subtitles."""

import asyncio
import logging
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from moviebox_api.v3.core import DownloadableCaptionFileDetails

from app.config import ALL_RESOLUTIONS
from app.core.client import get_client
from app.core.limiter import limiter
from app.services.download_service import fetch_all_pages_for_resolution
from app.services.stream_service import resolve_stream_for_episode
from app.utils.formatters import build_subtitle_summary, format_download_item
from app.utils.helpers import is_arabic_caption, is_dummy_video

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Media"])


@router.get("/get_download_links")
@limiter.limit("20/minute")
async def get_download_links(
    request: Request,
    subject_id: str = Query(...),
    resolution: int = Query(
        None,
        description="360 | 480 | 720 | 1080 — empty = all qualities",
    ),
):
    """
    جلب كل روابط التحميل — مع الترجمات المضمنة (subtitles_available,
    has_arabic_subtitle, arabic_subtitle_url, all_subtitles).
    """
    if not subject_id or not subject_id.strip():
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    if resolution is not None and resolution not in ALL_RESOLUTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"resolution غير صالح. الخيارات: {ALL_RESOLUTIONS}",
        )

    resolutions_to_fetch = [resolution] if resolution is not None else ALL_RESOLUTIONS

    try:
        seen: set[tuple] = set()
        download_links: list[dict] = []

        async with get_client() as client:
            tasks = [
                fetch_all_pages_for_resolution(client, subject_id, res)
                for res in resolutions_to_fetch
            ]
            results_per_resolution = await asyncio.gather(
                *tasks, return_exceptions=True
            )

            for res_idx, result in enumerate(results_per_resolution):
                if isinstance(result, Exception):
                    logger.error(
                        f"❌ {resolutions_to_fetch[res_idx]}p exception: {result}"
                    )
                    continue
                for raw_item in result:
                    formatted = format_download_item(raw_item)
                    # لو الـ ext_captions فاضية، نعمل fallback للـ get_subtitles
                    if not formatted["subtitles_available"] and formatted["resource_id"]:
                        try:
                            cap_fetcher = DownloadableCaptionFileDetails(client_session=client)
                            cap_data = await cap_fetcher.get_content(subject_id, formatted["resource_id"])
                            raw_caps = cap_data.get("extCaptions", [])
                            if raw_caps:
                                sub_info = build_subtitle_summary(raw_caps)
                                formatted.update(sub_info)
                        except Exception as e:
                            logger.warning(f"⚠️ subtitle fallback failed for {formatted['resource_id']}: {e}")
                    key = (
                        formatted.get("season"),
                        formatted.get("episode"),
                        formatted.get("resolution"),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    download_links.append(formatted)

            # ── حل وتحديث روابط البث الحقيقية (DASH) وإزالة الفيديو الوهمي ──
            episodes_to_resolve = set()
            for item in download_links:
                u = item.get("url") or ""
                needs_resolve = is_dummy_video(u) or not u or (".mpd" in u and not item.get("cookie"))
                if needs_resolve:
                    episodes_to_resolve.add((item.get("season", 0) or 0, item.get("episode", 0) or 0))

            if not download_links:
                episodes_to_resolve.add((0, 0))

            stream_map = {}
            if episodes_to_resolve:
                ep_tasks = [
                    resolve_stream_for_episode(client, subject_id, se, ep)
                    for se, ep in episodes_to_resolve
                ]
                resolved_list = await asyncio.gather(*ep_tasks, return_exceptions=True)
                for (se, ep), res_data in zip(episodes_to_resolve, resolved_list):
                    if isinstance(res_data, dict) and res_data.get("manifest_url"):
                        stream_map[(se, ep)] = res_data

            # تحديث العناصر بروابط البث المباشرة والـ Cookie
            for item in download_links:
                se_ep = (item.get("season", 0) or 0, item.get("episode", 0) or 0)
                u = item.get("url") or ""
                needs_resolve = is_dummy_video(u) or not u or (".mpd" in u and not item.get("cookie"))
                if se_ep in stream_map and needs_resolve:
                    s_info = stream_map[se_ep]
                    item["url"] = s_info["manifest_url"]
                    item["stream_type"] = "dash"
                    item["cookie"] = s_info["cookie"]
                    item["headers"] = s_info["headers"]
                    item["resolutions_available"] = s_info["resolutions"]
                    if s_info.get("size") and not item.get("size"):
                        item["size"] = s_info["size"]
                    if s_info.get("duration") and not item.get("duration"):
                        item["duration"] = s_info["duration"]
                    if s_info.get("codec") and not item.get("codec"):
                        item["codec"] = s_info["codec"]

            # في حال لم تكن هناك أي روابط في الأساس، ننشئ مدخلاً من stream_map
            if not download_links and stream_map:
                for (se, ep), s_info in stream_map.items():
                    download_links.append({
                        "url": s_info["manifest_url"],
                        "resolution": s_info["resolutions"][0] if s_info["resolutions"] else 1080,
                        "size": s_info.get("size"),
                        "season": se,
                        "episode": ep,
                        "resource_id": f"stream_{subject_id}_{se}_{ep}",
                        "codec": s_info.get("codec"),
                        "duration": s_info.get("duration", 0),
                        "source_url": None,
                        "stream_type": "dash",
                        "cookie": s_info["cookie"],
                        "headers": s_info["headers"],
                        "resolutions_available": s_info["resolutions"],
                        "subtitles_available": False,
                        "has_arabic_subtitle": False,
                        "arabic_subtitle_url": None,
                        "all_subtitles": [],
                        "total_languages": 0,
                    })

        # فلترة وحذف أي عنصر ما زال يحتوي على رابط الفيديو التنبيهي الوهمي
        download_links = [x for x in download_links if not is_dummy_video(x.get("url"))]

        if not download_links:
            raise HTTPException(
                status_code=404, detail="لم يتم العثور على روابط تحميل أو بث صالحة"
            )

        download_links.sort(key=lambda x: (
            x.get("season") or 0,
            x.get("episode") or 0,
            -(x.get("resolution") or 0),
        ))

        seasons = sorted({x["season"] for x in download_links if x.get("season")})
        episodes_per_season: dict = defaultdict(int)
        resolutions_found: set = set()
        any_arabic = False
        for x in download_links:
            s = x.get("season")
            if s:
                episodes_per_season[str(s)] = max(
                    episodes_per_season[str(s)], x.get("episode") or 0
                )
            if x.get("resolution"):
                resolutions_found.add(x["resolution"])
            if x.get("has_arabic_subtitle"):
                any_arabic = True

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "total_links": len(download_links),
            "seasons_found": seasons,
            "episodes_per_season": dict(episodes_per_season),
            "resolutions_found": sorted(resolutions_found),
            "has_arabic_subtitles": any_arabic,
            "download_links": download_links,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Download links error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب الروابط. حاول مرة أخرى.",
        )


@router.get("/get_stream")
@limiter.limit("30/minute")
async def get_stream(
    request: Request,
    subject_id: str = Query(..., description="معرف المحتوى في MovieBox"),
    season: int = Query(0, ge=0, description="رقم الموسم (0 للأفلام)"),
    episode: int = Query(0, ge=0, description="رقم الحلقة (0 للأفلام)"),
):
    """
    جلب رابط البث المباشر الموقّع (MPEG-DASH index.mpd) مع الـ Cookie و Headers المطلوبة لتشغيله في ExoPlayer.
    """
    subject_id = subject_id.strip()
    if not subject_id:
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    try:
        async with get_client() as client:
            stream_info = await resolve_stream_for_episode(
                client, subject_id, season, episode
            )

        if not stream_info:
            raise HTTPException(
                status_code=404, detail="لم يتم العثور على رابط بث لهذا المحتوى"
            )

        return JSONResponse(
            content={
                "status": "success",
                "subject_id": subject_id,
                "season": season,
                "episode": episode,
                "stream_url": stream_info["manifest_url"],
                "stream_type": "dash",
                "cookie": stream_info["cookie"],
                "headers": stream_info["headers"],
                "resolutions": stream_info["resolutions"],
                "codec": stream_info["codec"],
                "duration": stream_info["duration"],
                "size": stream_info["size"],
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get stream error: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500, detail="حدث خطأ في جلب رابط البث. حاول مرة أخرى."
        )


@router.get("/get_subtitles")
@limiter.limit("60/minute")
async def get_subtitles(
    request: Request,
    subject_id: str = Query(...),
    resource_id: str = Query(..., description="من حقل resource_id في روابط التحميل"),
):
    """
    جلب الترجمات لحلقة معينة عبر resource_id — endpoint احتياطي.
    """
    if not subject_id.strip() or not resource_id.strip():
        raise HTTPException(
            status_code=400, detail="subject_id و resource_id مطلوبان"
        )
    try:
        async with get_client() as client:
            caption_fetcher = DownloadableCaptionFileDetails(client_session=client)
            data = await caption_fetcher.get_content(subject_id, resource_id)

        raw_captions = data.get("extCaptions", [])
        sub_info = build_subtitle_summary(raw_captions)
        arabic_sub = next(
            (s for s in sub_info["all_subtitles"] if is_arabic_caption(s)), None
        )

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "resource_id": resource_id,
            "has_arabic": arabic_sub is not None,
            "arabic_subtitle": arabic_sub,
            "all_subtitles": sub_info["all_subtitles"],
            "total_languages": sub_info["total_languages"],
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Subtitles error: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ في جلب الترجمات.",
        )
