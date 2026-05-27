"""
تطبيق FastAPI بسيط للحصول على روابط التحميل من مكتبة moviebox-api
تم التصحيح لجلب كافة الجودات والحلقات للمسلسلات بشكل صحيح
"""

import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from moviebox_api.v3.core import DownloadableVideoFilesDetail
from moviebox_api.v3.http_client import MovieBoxHttpClient
from moviebox_api.v3.constants import ResolutionType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MovieBox FastAPI Backend",
    docs_url=None,
    redoc_url=None,
)

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Server started successfully!")

@app.get("/get_download_links")
async def get_download_links(
    subject_id: str = Query(..., description="معرف الفيلم/المسلسل"),
    resolution: int = Query(None, description="جودة الفيديو (مثلاً: 1080)، اتركه فارغاً لاستعراض كل الجودات")
):
    if not subject_id or not subject_id.strip():
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    # تجهيز قيمة الجودة
    if resolution is not None:
        try:
            res_enum = ResolutionType(resolution)
        except ValueError:
            res_enum = ResolutionType.UNSPECIFIED
    else:
        res_enum = ResolutionType.UNSPECIFIED

    try:
        async with MovieBoxHttpClient() as client:
            dl = DownloadableVideoFilesDetail(
                client_session=client,
                resolution=res_enum
            )
            
            all_items = []
            # 🚀 السر هنا: نستخدم get_content_model_all لجلب كل الصفحات والجودات
            async for content_model in dl.get_content_model_all(subject_id):
                # نصل إلى البيانات الخام من داخل الـ model
                if hasattr(content_model, 'list'):
                    all_items.extend(content_model.list)
                elif hasattr(content_model, 'items'):
                    all_items.extend(content_model.items)
                elif isinstance(content_model, dict):
                    items = content_model.get("list", [])
                    all_items.extend(items)

        download_links = []
        for item in all_items:
            # التعامل مع item سواء كان dict أو object
            if isinstance(item, dict):
                url = item.get("resourceLink")
                resolution_val = item.get("resolution")
                size = item.get("size")
                season = item.get("se")
                episode = item.get("ep")
            else:
                url = getattr(item, "resourceLink", None)
                resolution_val = getattr(item, "resolution", None)
                size = getattr(item, "size", None)
                season = getattr(item, "se", None)
                episode = getattr(item, "ep", None)

            if url:
                download_links.append({
                    "url": url,
                    "resolution": resolution_val,
                    "size": size,
                    "season": season,
                    "episode": episode,
                })

        if not download_links:
            raise HTTPException(status_code=404, detail="لم يتم العثور على روابط تحميل")

        return JSONResponse(content={
            "status": "success",
            "subject_id": subject_id,
            "total_links": len(download_links),
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
            "get_download_links": "/get_download_links?subject_id=ID&resolution=1080",
            "health_check": "/health"
        }
    })