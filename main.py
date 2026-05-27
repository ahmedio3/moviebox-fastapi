"""
تطبيق FastAPI بسيط للحصول على روابط التحميل من مكتبة moviebox-api
هذا التطبيق مصمم للنشر على Render.com (الخطة المجانية)
"""

import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import asyncio

# استيراد المكتبات المطلوبة من moviebox-api
from moviebox_api.v3.core import DownloadableVideoFilesDetail
from moviebox_api.v3.http_client import MovieBoxHttpClient

# إعداد logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# إنشاء تطبيق FastAPI بدون التوثيق التلقائي (لتوفير الموارد على Render)
app = FastAPI(
    title="MovieBox FastAPI Backend",
    description="Backend بسيط للحصول على روابط تحميل الأفلام",
    docs_url=None,  # تعطيل Swagger UI
    redoc_url=None,  # تعطيل ReDoc
)


@app.on_event("startup")
async def startup_event():
    """
    حدث البدء - يتم تنفيذه عند بدء السيرفر
    """
    logger.info("🚀 Server started successfully! MovieBox FastAPI Backend is running...")


@app.get("/get_download_links")
async def get_download_links(
    subject_id: str = Query(..., description="معرف الفيلم/المسلسل من MovieBox"),
    resolution: int = Query(None, description="جودة الفيديو المطلوبة (مثلاً: 1080، 720، 480)")
):
    """
    نقطة نهاية للحصول على روابط التحميل
    
    Parameters:
    -----------
    subject_id : str
        معرف الفيلم أو المسلسل (subject_id) من موقع MovieBox
    resolution : int, optional
        جودة الفيديو المطلوبة. إذا لم تحدد، سيتم إرجاع جميع الجودات المتاحة
    
    Returns:
    --------
    JSON تحتوي على قائمة روابط التحميل مع تفاصيلها
    
    Example:
    --------
    /get_download_links?subject_id=abc123&resolution=1080
    """
    
    try:
        # تحقق من أن subject_id ليس فارغاً
        if not subject_id or not subject_id.strip():
            raise HTTPException(
                status_code=400,
                detail="❌ subject_id مطلوب ولا يمكن أن يكون فارغاً"
            )
        
        logger.info(f"📥 طلب جديد: subject_id={subject_id}, resolution={resolution}")
        
        # استخدام MovieBoxHttpClient مع async with
        async with MovieBoxHttpClient() as client:
            # إنشاء كائن DownloadableVideoFilesDetail
            # هذا الكائن يقوم بجلب تفاصيل الملفات القابلة للتحميل
            dl = DownloadableVideoFilesDetail(
                client=client,
                resolution=resolution
            )
            
            # جلب محتوى التحميل من MovieBox
            logger.info(f"⏳ جاري جلب البيانات من MovieBox...")
            content = await dl.get_content(subject_id)
            
            # تحويل النتيجة إلى قائمة من dictionaries
            # نستخرج المعلومات المهمة من كل ملف
            download_links = []
            
            if content:
                # التعامل مع النتيجة (قد تكون قائمة أو كائن واحد)
                items = content if isinstance(content, list) else [content]
                
                for item in items:
                    try:
                        # استخراج البيانات من كل عنصر
                        link_data = {
                            "url": str(item.get("url", "") if isinstance(item, dict) else getattr(item, "url", "")),
                            "resolution": item.get("resolution", None) if isinstance(item, dict) else getattr(item, "resolution", None),
                            "size": item.get("size", None) if isinstance(item, dict) else getattr(item, "size", None),
                            "quality": item.get("quality", None) if isinstance(item, dict) else getattr(item, "quality", None),
                        }
                        
                        # تجاهل الروابط الفارغة
                        if link_data["url"]:
                            download_links.append(link_data)
                    except Exception as item_error:
                        logger.warning(f"⚠️  خطأ في معالجة عنصر: {item_error}")
                        continue
            
            if not download_links:
                raise HTTPException(
                    status_code=404,
                    detail=f"❌ لم يتم العثور على روابط تحميل لـ subject_id: {subject_id}"
                )
            
            logger.info(f"✅ تم جلب {len(download_links)} رابط بنجاح")
            
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "subject_id": subject_id,
                    "requested_resolution": resolution,
                    "total_links": len(download_links),
                    "download_links": download_links
                }
            )
        
    except HTTPException:
        # إعادة رفع HTTPException كما هي
        raise
    
    except Exception as e:
        # معالجة أي خطأ غير متوقع
        error_message = str(e)
        logger.error(f"❌ خطأ: {error_message}")
        
        raise HTTPException(
            status_code=500,
            detail=f"❌ حدث خطأ في السيرفر: {error_message}"
        )


@app.get("/health")
async def health_check():
    """
    نقطة نهاية للتحقق من حالة السيرفر (Health Check)
    استخدمها Render للتحقق من أن التطبيق يعمل بشكل صحيح
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "message": "✅ الخادم يعمل بشكل طبيعي"
        }
    )


@app.get("/")
async def root():
    """
    الصفحة الرئيسية - معلومات عن API
    """
    return JSONResponse(
        status_code=200,
        content={
            "name": "MovieBox FastAPI Backend",
            "version": "1.0.0",
            "description": "Backend بسيط للحصول على روابط تحميل الأفلام والمسلسلات",
            "endpoints": {
                "get_download_links": "/get_download_links?subject_id=ID&resolution=1080",
                "health_check": "/health"
            },
            "usage": "استخدم /get_download_links?subject_id=YOUR_ID للحصول على روابط التحميل"
        }
    )


# إذا تم تشغيل الملف مباشرة (للاختبار المحلي)
if __name__ == "__main__":
    import uvicorn
    
    # تشغيل السيرفر محلياً على المنفذ 8000
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
