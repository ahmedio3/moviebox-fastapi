"""
تطبيق FastAPI لجلب روابط التحميل مع دعم الدبلجة والترجمة
"""

import logging
import asyncio
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from moviebox_api.v3.core import DownloadableVideoFilesDetail, ItemDetails
from moviebox_api.v3.http_client import MovieBoxHttpClient
from moviebox_api.v3.constants import ResolutionType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MovieBox FastAPI Backend", docs_url=None, redoc_url=None)

RESOLUTIONS = [360, 480, 720, 1080]

class EpisodeDownload(DownloadableVideoFilesDetail):
    def __init__(self, *args, season=None, episode=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._season = season
        self._episode = episode

    def _create_params(self, subject_id):
        params = super()._create_params(subject_id)
        if self._season is not None:
            params["se"] = self._season
        if self._episode is not None:
            params["ep"] = self._episode
        return params

async def fetch_episode_resolution(client, subject_id, season, episode, res_value):
    try:
        dl = EpisodeDownload(
            client_session=client,
            resolution=ResolutionType(res_value),
            season=season,
            episode=episode,
        )
        data = await dl.get_content(subject_id)
        return data.get("list", [])
    except Exception as e:
        logger.warning(f"⚠️ S{season}E{episode} @ {res_value}p فشل: {e}")
        return []

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Server started successfully!")

@app.get("/get_download_links")
async def get_download_links(
    subject_id: str = Query(..., description="معرف الفيلم/المسلسل"),
    resolution: int = Query(None, description="جودة الفيديو"),
    dub: str = Query(None, description="فلترة حسب لغة الدبلجة (مثلاً: Original, Hindi)")
):
    if not subject_id or not subject_id.strip():
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    if resolution is not None:
        try:
            res_enum = ResolutionType(resolution)
        except ValueError:
            res_enum = ResolutionType.UNSPECIFIED
    else:
        res_enum = ResolutionType.UNSPECIFIED

    try:
        async with MovieBoxHttpClient() as client:
            # جلب تفاصيل الدبلجات المتاحة (للاستخدام المستقبلي)
            available_dubs = []
            try:
                item_details = ItemDetails(client_session=client)
                details = await item_details.get_content_model(subject_id)
                for d in getattr(details, 'dubs', []):
                    if hasattr(d, 'lan_name'):
                        available_dubs.append(d.lan_name)
            except Exception as e:
                logger.warning(f"⚠️ تعذر جلب قائمة الدبلجات: {e}")

            # جلب الروابط الأساسية
            dl = DownloadableVideoFilesDetail(
                client_session=client,
                resolution=res_enum
            )
            data = await dl.get_content(subject_id)
            base_items = data.get("list", [])

            is_series = any(
                item.get("se", 0) != 0 or item.get("ep", 0) != 0
                for item in base_items
            )

            all_items = list(base_items)

            if is_series and res_enum == ResolutionType.UNSPECIFIED:
                episodes = [
                    (item.get("se", 0), item.get("ep", 0))
                    for item in base_items
                ]
                tasks = [
                    fetch_episode_resolution(client, subject_id, se, ep, res)
                    for res in RESOLUTIONS[1:]
                    for (se, ep) in episodes
                ]
                results = await asyncio.gather(*tasks)
                for chunk in results:
                    all_items.extend(chunk)

        download_links = []
        seen = set()
        for item in all_items:
            key = (item.get("se"), item.get("ep"), item.get("resolution"), item.get("dub", ""))
            if key in seen:
                continue
            seen.add(key)
            link = {
                "url": item.get("resourceLink"),
                "resolution": item.get("resolution"),
                "size": item.get("size"),
                "season": item.get("se"),
                "episode": item.get("ep"),
                "dub": item.get("dub", "Unknown")  # ✅ الحل: إظهار لغة الدبلجة
            }
            # فلترة حسب اللغة إذا طلب المستخدم
            if dub and link["dub"].lower() != dub.lower():
                continue
            download_links.append(link)

        if not download_links:
            raise HTTPException(status_code=404, detail="لم يتم العثور على روابط تحميل")

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "total_links": len(download_links),
            "available_dubs": available_dubs,  # لإظهارها في التطبيق
            "download_links": download_links
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "healthy", "message": "✅ الخادم يعمل"})

@app.get("/")
async def root():
    return JSONResponse(content={
        "name": "MovieBox FastAPI Backend",
        "endpoints": {
            "get_download_links": "/get_download_links?subject_id=ID&resolution=1080&dub=Original",
            "health_check": "/health"
        }
    })