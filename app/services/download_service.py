"""Download service for fetching and aggregating downloadable video files across pages."""

import logging

from moviebox_api.v3.constants import ResolutionType
from moviebox_api.v3.core import DownloadableVideoFilesDetail
from moviebox_api.v3.http_client import MovieBoxHttpClient

from app.config import PER_PAGE_OPTIONS

logger = logging.getLogger(__name__)


async def fetch_all_pages_for_resolution(
    client: MovieBoxHttpClient,
    subject_id: str,
    resolution: int,
) -> list[dict]:
    """يجيب كل الحلقات لـ resolution معين مع استخراج الـ captions كمان."""
    for per_page_val in PER_PAGE_OPTIONS:
        items: list[dict] = []
        try:
            res_enum = ResolutionType(resolution)
            dl = DownloadableVideoFilesDetail(
                client_session=client,
                resolution=res_enum,
                per_page=per_page_val,
            )

            page_count = 0
            async for page_model in dl.get_content_model_all(subject_id):
                page_count += 1
                for video_file in page_model.list:
                    ext_caps = video_file.ext_captions or []
                    item_dict = {
                        "resourceLink": str(video_file.resource_link) if video_file.resource_link else None,
                        "resolution": int(video_file.resolution) if video_file.resolution else 0,
                        "size": str(video_file.size) if video_file.size else None,
                        "se": int(video_file.season) if video_file.season else 0,
                        "ep": int(video_file.episode) if video_file.episode else 0,
                        "resourceId": str(video_file.resource_id) if video_file.resource_id else None,
                        "codecName": getattr(video_file, "codec_name", None) or getattr(video_file, "codecName", None),
                        "duration": int(getattr(video_file, "duration", 0) or 0),
                        "sourceUrl": str(getattr(video_file, "source_url", "") or "") or None,
                        # ── الترجمات المضمنة مع الملف (إن وجدت) ──
                        "extCaptions": [
                            {
                                "id": getattr(cap, "id", ""),
                                "lan": getattr(cap, "lan", "") or "",
                                "lanName": getattr(cap, "lan_name", "") or "",
                                "url": str(getattr(cap, "url", "") or ""),
                                "size": int(getattr(cap, "size", 0) or 0),
                                "delay": int(getattr(cap, "delay", 0) or 0),
                            }
                            for cap in ext_caps
                        ],
                    }
                    items.append(item_dict)

                logger.info(
                    f"📄 {resolution}p — page {page_count}: {len(page_model.list)} items"
                )

            logger.info(f"✅ {resolution}p done: {len(items)} links in {page_count} pages")
            return items

        except ValueError as ve:
            logger.warning(
                f"⚠️ {resolution}p: per_page={per_page_val} rejected ({ve}) — trying next"
            )
            continue

        except Exception as e:
            logger.error(f"❌ {resolution}p error: {type(e).__name__}: {e}")
            if per_page_val == PER_PAGE_OPTIONS[-1]:
                return []
            continue

    return []
