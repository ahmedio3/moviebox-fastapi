"""Media endpoints for download links, MPEG-DASH streaming, and subtitles."""

import asyncio
import logging
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from moviebox_api.v3.core import DownloadableCaptionFileDetails, SeasonDetails
from moviebox_api.v3.urls import RESOURCE_PATH

from app.config import ALL_RESOLUTIONS
from app.core.client import get_client
from app.core.limiter import limiter
from app.services.download_service import (
    fetch_page_for_resolution,
)
from app.services.stream_service import resolve_stream_for_episode
from app.utils.formatters import build_subtitle_summary, format_download_item
from app.utils.helpers import is_arabic_caption, is_dummy_video

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Media"])


@router.get("/get_download_links")
@limiter.limit("30/minute")
async def get_download_links(
    request: Request,
    subject_id: str = Query(..., description="معرف المحتوى في MovieBox"),
    resolution: int = Query(
        None,
        description="360 | 480 | 720 | 1080 — empty = all qualities",
    ),
    season: int = Query(None, description="رقم الموسم (0 للأفلام)"),
    episode: int = Query(None, description="رقم الحلقة (0 للأفلام)"),
    page: int = Query(1, ge=1, description="رقم صفحة الحلقات (شريحة)"),
    limit: int = Query(10, ge=1, le=50, description="الحد الأقصى لعدد الحلقات في الطلب (افتراضي 10)"),
):
    """
    جلب روابط التحميل والبث مع الترجمات المضمنة.
    يدعم جلب حلقة محددة (season + episode) فوراً، أو شريحة حلقات (page + limit، افتراضي 10 حلقات).
    """
    subject_id = subject_id.strip()
    if not subject_id:
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    if resolution is not None and resolution not in ALL_RESOLUTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"resolution غير صالح. الخيارات: {ALL_RESOLUTIONS}",
        )

    try:
        download_links: list[dict] = []
        has_more = False

        async with get_client() as client:
            meta_res = resolution if resolution is not None else 720

            # 1. الاستعلام عن تفاصيل المواسم والحلقات الدقيقة من SeasonDetails
            is_movie = False
            seasons_map: dict[int, int] = {}
            default_season = 0
            try:
                sd_fetcher = SeasonDetails(client_session=client)
                sd_data = await sd_fetcher.get_content(subject_id)
                subj_type = sd_data.get("subjectType", 1)
                raw_seasons = sd_data.get("seasons", [])
                if subj_type == 1 or not raw_seasons or (len(raw_seasons) == 1 and raw_seasons[0].get("se") == 0 and raw_seasons[0].get("maxEp") == 0):
                    is_movie = True
                else:
                    for s_item in raw_seasons:
                        s_num = s_item.get("se", 0)
                        max_ep = s_item.get("maxEp", 0)
                        seasons_map[s_num] = max_ep
                    if seasons_map:
                        default_season = min(seasons_map.keys())
            except Exception as e:
                logger.warning(f"⚠️ Failed to fetch SeasonDetails for {subject_id}: {e}")
                if season is not None and season > 0:
                    seasons_map[season] = 999
                else:
                    is_movie = True

            target_season = season if (season is not None and season > 0) else (0 if is_movie else default_season)
            max_ep = seasons_map.get(target_season, 0)

            # 2. تحديد الحلقات المستهدفة وحالة has_more
            target_episodes: list[tuple[int, int]] = []
            if is_movie:
                target_episodes = [(0, 0)]
                has_more = False
            elif episode is not None:
                target_episode = episode
                if max_ep > 0 and target_episode > max_ep:
                    raise HTTPException(
                        status_code=404,
                        detail=f"الحلقة {target_episode} غير متوفرة في الموسم {target_season} (أقصى حلقة هي {max_ep})"
                    )
                target_episodes = [(target_season, target_episode)]
                has_more = False
            else:
                if max_ep > 0:
                    start_ep = (page - 1) * limit + 1
                    end_ep = min(start_ep + limit - 1, max_ep)
                    if start_ep <= max_ep:
                        target_episodes = [(target_season, ep) for ep in range(start_ep, end_ep + 1)]
                        has_more = (end_ep < max_ep)
                    else:
                        target_episodes = []
                        has_more = False
                else:
                    start_ep = (page - 1) * limit + 1
                    end_ep = start_ep + limit - 1
                    target_episodes = [(target_season, ep) for ep in range(start_ep, end_ep + 1)]
                    has_more = True

            # 3. جلب البيانات الوصفية (resourceId والترجمات) للشريحة عبر RESOURCE_PATH
            meta_by_ep: dict[tuple[int, int], dict] = {}
            if target_episodes:
                try:
                    res_meta = await client.get_from_api(
                        RESOURCE_PATH,
                        params={"subjectId": subject_id, "se": target_season, "page": page}
                    )
                    res_items = res_meta.get("list", []) if isinstance(res_meta, dict) else []
                    for it in res_items:
                        it_key = (it.get("se", target_season), it.get("ep", 0))
                        if it_key not in meta_by_ep:
                            meta_by_ep[it_key] = it
                except Exception as ex:
                    logger.warning(f"⚠️ Failed to fetch RESOURCE_PATH for {subject_id} S{target_season} P{page}: {ex}")

            # 4. حل روابط البث المباشر (DASH) بالتوازي لجميع حلقات الشريحة
            stream_tasks = [
                resolve_stream_for_episode(
                    client,
                    subject_id,
                    se,
                    ep,
                    fetch_mpd=(len(target_episodes) == 1)
                )
                for se, ep in target_episodes
            ]
            streams_res = await asyncio.gather(*stream_tasks, return_exceptions=True)
            stream_map = {
                ep_key: res_d
                for ep_key, res_d in zip(target_episodes, streams_res)
                if isinstance(res_d, dict) and res_d.get("manifest_url")
            }

            # 5. تشكيل قائمة روابط التحميل والبث
            for se, ep in target_episodes:
                ep_key = (se, ep)
                matching_item = meta_by_ep.get(ep_key)

                sub_info = {
                    "subtitles_available": False,
                    "has_arabic_subtitle": False,
                    "arabic_subtitle_url": None,
                    "all_subtitles": [],
                    "total_languages": 0
                }
                if matching_item and matching_item.get("extCaptions"):
                    sub_info = build_subtitle_summary(matching_item["extCaptions"])

                if ep_key in stream_map:
                    s_info = stream_map[ep_key]
                    avail_resolutions = s_info.get("resolutions") or [meta_res]
                    if resolution is not None:
                        qualities_to_emit = [resolution] if resolution in avail_resolutions else [avail_resolutions[0]]
                    else:
                        qualities_to_emit = avail_resolutions

                    for q in qualities_to_emit:
                        q_size = s_info.get("sizes", {}).get(q) or s_info.get("size")
                        download_links.append({
                            "url": s_info["manifest_url"],
                            "resolution": q,
                            "size": q_size,
                            "season": se,
                            "episode": ep,
                            "resource_id": matching_item.get("resourceId") if matching_item else f"stream_{subject_id}_{se}_{ep}",
                            "codec": s_info.get("codec"),
                            "duration": s_info.get("duration", 0),
                            "source_url": None,
                            "stream_type": "dash",
                            "cookie": s_info["cookie"],
                            "headers": s_info["headers"],
                            "resolutions_available": s_info["resolutions"],
                            **sub_info,
                        })
                elif matching_item and matching_item.get("resourceLink") and not is_dummy_video(matching_item.get("resourceLink")):
                    formatted = format_download_item(matching_item)
                    formatted.update(sub_info)
                    download_links.append(formatted)

        # فلترة وحذف أي روابط وهمية قد تكون تسللت
        download_links = [x for x in download_links if not is_dummy_video(x.get("url"))]

        if not download_links:
            if is_movie:
                raise HTTPException(
                    status_code=404, detail="لم يتم العثور على روابط تحميل أو بث صالحة لهذا الفيلم"
                )
            if episode is not None:
                raise HTTPException(
                    status_code=404, detail=f"لم يتم العثور على روابط تحميل صالحة للحلقة {episode}"
                )
            if page == 1:
                raise HTTPException(
                    status_code=404, detail="لم يتم العثور على روابط تحميل أو بث صالحة"
                )
            # بالنسبة للصفحات التالية المنتهية، إرجاع قائمة فارغة مع has_more: false بدلاً من 404
            return JSONResponse(content={
                "status": "success",
                "subject_id": subject_id,
                "total_links": 0,
                "current_page": page,
                "limit": limit,
                "has_more": False,
                "seasons_found": sorted(seasons_map.keys()) if seasons_map else ([target_season] if target_season else []),
                "episodes_per_season": {str(k): v for k, v in seasons_map.items()} if seasons_map else ({str(target_season): max_ep} if target_season else {}),
                "resolutions_found": [],
                "has_arabic_subtitles": False,
                "download_links": [],
            })

        # ترتيب الروابط
        download_links.sort(key=lambda x: (
            x.get("season") or 0,
            x.get("episode") or 0,
            -(x.get("resolution") or 0),
        ))

        seasons = sorted(seasons_map.keys()) if seasons_map else sorted({x["season"] for x in download_links if x.get("season")})
        episodes_per_season: dict = defaultdict(int)
        if seasons_map:
            for s_num, m_ep in seasons_map.items():
                episodes_per_season[str(s_num)] = m_ep
        else:
            for x in download_links:
                s = x.get("season")
                if s:
                    episodes_per_season[str(s)] = max(
                        episodes_per_season[str(s)], x.get("episode") or 0
                    )
        resolutions_found: set = set()
        any_arabic = False
        for x in download_links:
            if x.get("resolution"):
                resolutions_found.add(x["resolution"])
            if x.get("has_arabic_subtitle"):
                any_arabic = True

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "total_links": len(download_links),
            "current_page": page,
            "limit": limit,
            "has_more": has_more,
            "seasons_found": seasons,
            "episodes_per_season": dict(episodes_per_season),
            "resolutions_found": sorted(resolutions_found),
            "has_arabic_subtitles": any_arabic,
            "download_links": download_links,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Download links error: {type(e).__name__}: {e}")
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
