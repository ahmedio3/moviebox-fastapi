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
            # الجودة المرجعية لجلب بيانات الحلقات الوصفية والترجمات
            meta_res = resolution if resolution is not None else 720

            # ─────────────────────────────────────────────────────────────
            # 1. حالة طلب حلقة محددة (مثال: الموسم 1 الحلقة 15 أو فيلم 0, 0)
            # ─────────────────────────────────────────────────────────────
            if episode is not None:
                target_season = season if season is not None else 0
                target_episode = episode

                # صفحة MovieBox التي تحتوي على هذه الحلقة (كل صفحة فيها 20 حلقة)
                mb_page = ((target_episode - 1) // 20) + 1 if target_episode > 0 else 1
                raw_page_items = await fetch_page_for_resolution(
                    client, subject_id, meta_res, page=mb_page, per_page=20
                )
                if not raw_page_items and mb_page != 1:
                    raw_page_items = await fetch_page_for_resolution(
                        client, subject_id, meta_res, page=1, per_page=20
                    )

                matched_item = next(
                    (it for it in raw_page_items if it.get("ep") == target_episode and (season is None or it.get("se") == target_season)),
                    None
                )

                # حل رابط البث المباشر والكوكيز للحلقة المستهدفة
                s_info = await resolve_stream_for_episode(
                    client, subject_id, target_season, target_episode
                )

                # استخراج الترجمات للحلقة
                sub_info = {"subtitles_available": False, "has_arabic_subtitle": False, "arabic_subtitle_url": None, "all_subtitles": [], "total_languages": 0}
                if matched_item and matched_item.get("extCaptions"):
                    sub_info = build_subtitle_summary(matched_item["extCaptions"])
                elif matched_item and matched_item.get("resourceId"):
                    try:
                        cap_fetcher = DownloadableCaptionFileDetails(client_session=client)
                        cap_data = await cap_fetcher.get_content(subject_id, matched_item["resourceId"])
                        raw_caps = cap_data.get("extCaptions", [])
                        if raw_caps:
                            sub_info = build_subtitle_summary(raw_caps)
                    except Exception as e:
                        logger.warning(f"⚠️ Subtitle fallback failed for {matched_item.get('resourceId')}: {e}")

                if s_info and s_info.get("manifest_url"):
                    avail_resolutions = s_info.get("resolutions") or [meta_res]
                    qualities_to_emit = [resolution] if (resolution is not None and resolution in avail_resolutions) else (avail_resolutions if resolution is None else [avail_resolutions[0]])

                    for q in qualities_to_emit:
                        q_size = s_info.get("sizes", {}).get(q) or s_info.get("size")
                        download_links.append({
                            "url": s_info["manifest_url"],
                            "resolution": q,
                            "size": q_size,
                            "season": target_season,
                            "episode": target_episode,
                            "resource_id": matched_item.get("resourceId") if matched_item else f"stream_{subject_id}_{target_season}_{target_episode}",
                            "codec": s_info.get("codec"),
                            "duration": s_info.get("duration", 0),
                            "source_url": None,
                            "stream_type": "dash",
                            "cookie": s_info["cookie"],
                            "headers": s_info["headers"],
                            "resolutions_available": s_info["resolutions"],
                            **sub_info,
                        })
                elif matched_item and matched_item.get("resourceLink") and not is_dummy_video(matched_item.get("resourceLink")):
                    formatted = format_download_item(matched_item)
                    formatted.update(sub_info)
                    download_links.append(formatted)

            # ─────────────────────────────────────────────────────────────
            # 2. حالة تصفح الحلقات (شريحة بحد أقصى limit، افتراضي 10 حلقات)
            # ─────────────────────────────────────────────────────────────
            else:
                # حساب صفحات MovieBox المطلوبة للنافذة المحددة
                # مثلاً limit=10, page=1 -> الحلقات 1 إلى 10 -> صفحة MovieBox رقم 1
                # limit=10, page=2 -> الحلقات 11 إلى 20 -> صفحة MovieBox رقم 1
                # limit=10, page=3 -> الحلقات 21 إلى 30 -> صفحة MovieBox رقم 2
                start_ep_idx = (page - 1) * limit
                end_ep_idx = start_ep_idx + limit

                mb_page_start = (start_ep_idx // 20) + 1
                mb_page_end = ((end_ep_idx - 1) // 20) + 1

                # جلب صفحات MovieBox المطلوبة فقط (صفحة واحدة أو اثنتين على الأكثر)
                fetch_tasks = [
                    fetch_page_for_resolution(client, subject_id, meta_res, page=p, per_page=20)
                    for p in range(mb_page_start, mb_page_end + 1)
                ]
                pages_data = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                raw_items = []
                for p_res in pages_data:
                    if isinstance(p_res, list):
                        raw_items.extend(p_res)

                # إذا كانت النتيجة فارغة والموسم ليس 1، نجرب الصفحة 1 كـ Fallback
                if not raw_items and mb_page_start != 1:
                    raw_items = await fetch_page_for_resolution(
                        client, subject_id, meta_res, page=1, per_page=20
                    )

                # فلترة بالموسم إذا حُدد
                if season is not None:
                    raw_items = [it for it in raw_items if it.get("se") == season]

                # تجميع الحلقات الفريدة بالترتيب
                episodes_order: list[tuple[int, int]] = []
                items_by_ep: dict[tuple[int, int], list[dict]] = defaultdict(list)
                for it in raw_items:
                    ep_key = (it.get("se", 0) or 0, it.get("ep", 0) or 0)
                    if ep_key not in items_by_ep:
                        episodes_order.append(ep_key)
                    items_by_ep[ep_key].append(it)

                # تحديد الشريحة المستهدفة (بحد أقصى limit حلقات)
                offset_in_batch = start_ep_idx % 20 if mb_page_start == mb_page_end else (start_ep_idx - (mb_page_start - 1) * 20)
                # إذا كانت الحلقات المجموعة أقل من الإزاحة، نأخذ من البداية
                if offset_in_batch >= len(episodes_order):
                    target_episodes = episodes_order[:limit]
                else:
                    target_episodes = episodes_order[offset_in_batch : offset_in_batch + limit]

                # هل توجد حلقات تالية؟
                has_more = (len(episodes_order) > (offset_in_batch + len(target_episodes))) or (len(raw_items) >= 20)

                # في حال لم نجد أي حلقات (مثل الأفلام أو عناصر خاصة)، نعتبر الهدف (0, 0)
                if not target_episodes:
                    target_episodes = [(season or 0, 0)]

                # ── فك روابط البث الحقيقية بالتوازي للشريحة المحددة فقط (<= 10 طلبات) ──
                stream_tasks = [
                    resolve_stream_for_episode(client, subject_id, se, ep)
                    for se, ep in target_episodes
                ]
                streams_res = await asyncio.gather(*stream_tasks, return_exceptions=True)
                stream_map = {
                    ep_key: res_d
                    for ep_key, res_d in zip(target_episodes, streams_res)
                    if isinstance(res_d, dict) and res_d.get("manifest_url")
                }

                # ── جلب الترجمات بالتوازي للحلقات التي تفتقر إليها ──
                cap_tasks = {}
                for ep_key in target_episodes:
                    matching_items = items_by_ep.get(ep_key, [])
                    first_item = matching_items[0] if matching_items else None
                    if first_item and not first_item.get("extCaptions") and first_item.get("resourceId"):
                        cap_tasks[ep_key] = first_item.get("resourceId")

                cap_results = {}
                if cap_tasks:
                    cap_fetcher = DownloadableCaptionFileDetails(client_session=client)
                    cap_coros = [cap_fetcher.get_content(subject_id, rid) for rid in cap_tasks.values()]
                    cap_raw_list = await asyncio.gather(*cap_coros, return_exceptions=True)
                    for ep_k, raw_c in zip(cap_tasks.keys(), cap_raw_list):
                        if isinstance(raw_c, dict) and raw_c.get("extCaptions"):
                            cap_results[ep_k] = build_subtitle_summary(raw_c["extCaptions"])

                # ── تشكيل عناصر الروابط النهائية ──
                for se, ep in target_episodes:
                    ep_key = (se, ep)
                    matching_items = items_by_ep.get(ep_key, [])
                    first_item = matching_items[0] if matching_items else None

                    # استخراج الترجمة
                    sub_info = {"subtitles_available": False, "has_arabic_subtitle": False, "arabic_subtitle_url": None, "all_subtitles": [], "total_languages": 0}
                    if first_item and first_item.get("extCaptions"):
                        sub_info = build_subtitle_summary(first_item["extCaptions"])
                    elif ep_key in cap_results:
                        sub_info = cap_results[ep_key]

                    # في حال تم حل رابط البث المباشر DASH
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
                                "resource_id": first_item.get("resourceId") if first_item else f"stream_{subject_id}_{se}_{ep}",
                                "codec": s_info.get("codec"),
                                "duration": s_info.get("duration", 0),
                                "source_url": None,
                                "stream_type": "dash",
                                "cookie": s_info["cookie"],
                                "headers": s_info["headers"],
                                "resolutions_available": s_info["resolutions"],
                                **sub_info,
                            })
                    # في حال لم يتم حل البث، نستخدم الروابط الأصلية إذا لم تكن فيديو تحذيري وهمي
                    elif matching_items:
                        for it in matching_items:
                            if not is_dummy_video(it.get("resourceLink")):
                                formatted = format_download_item(it)
                                formatted.update(sub_info)
                                download_links.append(formatted)

        # فلترة وحذف أي روابط وهمية قد تكون تسللت
        download_links = [x for x in download_links if not is_dummy_video(x.get("url"))]

        if not download_links:
            raise HTTPException(
                status_code=404, detail="لم يتم العثور على روابط تحميل أو بث صالحة"
            )

        # ترتيب الروابط
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
