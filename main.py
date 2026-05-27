"""
تطبيق FastAPI بسيط للحصول على روابط التحميل من مكتبة moviebox-api
هذا التطبيق مصمم للنشر على Render.com (الخطة المجانية)
"""

import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

# استيراد المكتبات المطلوبة من moviebox-api
from moviebox_api.v3.core import DownloadableVideoFilesDetail

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
    subject_id: str = Query(..., description="معرف الفيلم/المسلسل"),
    resolution: int = Query(1080, description="دقة الفيديو")  # جعل 1080 افتراضية لتسهيل التجربة
):
    """
    نقطة نهاية للحصول على روابط التحميل
    
    Parameters:
    -----------
    subject_id : str
        معرف الفيلم أو المسلسل (subject_id) من موقع MovieBox
    resolution : int
        دقة الفيديو المطلوبة (الافتراضية: 1080)
    
    Returns:
    --------
    JSON تحتوي على قائمة روابط التحميل مع تفاصيلها
    
    Example:
    --------
    /get_download_links?subject_id=abc123&resolution=1080
    """
    
    try:
        # التحقق من أن subject_id ليس فارغاً
        if not subject_id or not subject_id.strip():
            raise HTTPException(
                status_code=400,
                detail="❌ subject_id مطلوب ولا يمكن أن يكون فارغاً"
            )
        
        logger.info(f"📥 طلب جديد: subject_id={subject_id}, resolution={resolution}")
        
        # 1. إنشاء الكائن الذي يبحث عن روابط التحميل مع ضبط الدقة
        dl = DownloadableVideoFilesDetail(
            resolution=resolution
        )
        
        # 2. تشغيل الجلب داخل بيئة async
        async with dl as dl_session:
            # 3. جلب البيانات الحقيقية - هذه الدالة هي كل شيء!
            #    تقوم بتسجيل الدخول تلقائياً، جلب الروابط، وحل التحديات الأمنية.
            #    ترجع قائمة من كائنات VideoFileMetadata
            logger.info(f"⏳ جاري جلب البيانات من MovieBox...")
            video_files = await dl_session.fetch(subject_id)
            
            # 4. تحويل النتيجة إلى JSON
            download_links = []
            for video in video_files:
                # تحويل الكائن إلى dict باستخدام دالة model_dump() المدمجة
                video_dict = video.model_dump()
                download_links.append({
                    "url": video_dict.get("resource_link"),
                    "resolution": video_dict.get("resolution"),
                    "size": video_dict.get("size"),
                    "season": video_dict.get("se"),
                    "episode": video_dict.get("ep"),
                })
            
            if not download_links:
                logger.warning(f"⚠️ لم يتم العثور على روابط لـ subject_id: {subject_id}")
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
