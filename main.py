"""
تطبيق FastAPI بسيط للحصول على روابط التحميل من مكتبة moviebox-api
هذا التطبيق مصمم للنشر على Render.com (الخطة المجانية)
"""

import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from moviebox_api.v3.core import DownloadableVideoFilesDetail
from moviebox_api.v3.http_client import MovieBoxHttpClient

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
    resolution: int = Query(1080, description="دقة الفيديو (مثلاً: 1080)")
):
    if not subject_id or not subject_id.strip():
        raise HTTPException(status_code=400, detail="subject_id مطلوب")

    try:
        # 1. فتح اتصال HTTP مع MovieBox
        async with MovieBoxHttpClient() as client:
            # 2. إنشاء كائن تحميل الفيديوهات وتمرير العميل والدقة
            dl = DownloadableVideoFilesDetail(
                client_session=client,
                resolution=resolution
            )
            # 3. جلب البيانات
            data = await dl.get_content(subject_id)

        # 4. استخراج الروابط (البيانات تحت مفتاح "list")
        items = data.get("list", [])
        download_links = []
        for item in items:
            download_links.append({
                "url": item.get("resourceLink"),
                "resolution": item.get("resolution"),
                "size": item.get("size"),
                "season": item.get("se"),
                "episode": item.get("ep"),
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