"""
تطبيق FastAPI بسيط للحصول على روابط التحميل من مكتبة moviebox-api
تم التصحيح النهائي لمعالجة مخرجات get_content_model_all بشكل صحيح
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
            # استخدام get_content_model_all لجلب كل الصفحات
            async for content_model in dl.get_content_model_all(subject_id):
                # ✅ التصحيح: RootDownloadableFilesDetailModel يحتوي على list من كائنات VideoFileMetadata
                if hasattr(content_model, 'root'):
                    # بعض النماذج قد تكون مغلفة
                    items = content_model.root
                    if isinstance(items, list):
                        all_items.extend(items)
                elif hasattr(content_model, 'list'):
                    all_items.extend(content_model.list)
                elif isinstance(content_model, list):
                    all_items.extend(content_model)

        download_links = []
        for item in all_items:
            try:
                # التعامل مع item ككائن VideoFileMetadata (يحتوي على attributes)
                if hasattr(item, 'resource_link'):
                    url = item.resource_link
                elif hasattr(item, 'resourceLink'):
                    url = item.resourceLink
                else:
                    url = None

                resolution_val = getattr(item, 'resolution', None)
                size = getattr(item, 'size', None)
                season = getattr(item, 'se', None) or getattr(item, 'season', None)
                episode = getattr(item, 'ep', None) or getattr(item, 'episode', None)

                if url:
                    download_links.append({
                        "url": url,
                        "resolution": resolution_val,
                        "size": size,
                        "season": season,
                        "episode": episode,
                    })
            except Exception as item_error:
                logger.warning(f"⚠️ خطأ في معالجة عنصر: {item_error}")
                continue

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