# تقرير تسليم تشخيص مشكلة المقطع الثابت (طلب تحديث التطبيق) والحل الجذري

> **تاريخ التقرير:** 29 أكتوبر 2026  
> **المشروع:** `ahmedio3/moviebox-fastapi`  
> **الملف المستهدف للآجنت القادم:** هذا التقرير يوضح السبب الجذري الدقيق والحل المباشر دون الحاجة لإعادة البحث من الصفر.

---

## 1. السبب الجذري الدقيق (Root Cause)

1. **تحديث أمني من سيرفر MovieBox / AOneRoom (`api6.aoneroom.com`):**  
   في تاريخ **10 أكتوبر 2026**، قام سيرفر MovieBox بإطلاق نسخة جديدة وحظر الإصدارات القديمة من خلال إرجاع فيديو تحذيري وهمي يطلب من المستخدم «تحديث تطبيق أندرويد» لأي طلب يأتي من إصدار قديم.

2. **بيانات الفيديو الوهمي الجديد:**  
   * **الرابط:** `https://macdn.aoneroom.com/other/2026/10/10/80da52722ee7de7a4303290af6783424.mp4`
   * **الهاش الجديد:** `80da52722ee7de7a4303290af6783424` (الهاش القديم كان `b164fbfb4347792950bdfbfb563d39d9`).
   * **المدة:** 23 ثانية.
   * **الحجم:** 824,720 بايت (~824 KB).
   * **حقل signCookie:** يعود فارغاً `""` عند كشف أن الطلب من تطبيق قديم، مما يعطل فك روابط DASH.

3. **كيف يكشف السيرفر الطلب؟**  
   مكتبة `moviebox-api` المثبتة حالياً ترسل في كل طلب الهيدرز التالية:
   * `version_code`: `50020042`
   * `version_name`: `3.0.03.0529.03`
   * غياب الهيدر الإلزامي الجديد `X-M-Version` المعتمد في إصدارات v4.0.02+.

---

## 2. ما يحتاج الآجنت القادم لفعله مباشرة (Action Plan)

### الخطوة 1: تحديث فلترة الفيديوهات الوهمية في كود الـ API
في ملف [`app/config.py`](file:///c:/Users/HP/Documents/moviebox-fastapi/app/config.py) و [`app/utils/helpers.py`](file:///c:/Users/HP/Documents/moviebox-fastapi/app/utils/helpers.py):
* استبدال أو توسيع `DUMMY_VIDEO_HASH` ليدعم قائمة هاشات:
  ```python
  DUMMY_VIDEO_HASHES = [
      "b164fbfb4347792950bdfbfb563d39d9", # الفيديو القديم (04/09/2026)
      "80da52722ee7de7a4303290af6783424", # الفيديو الجديد (10/10/2026)
  ]
  ```
* تحديث دالة `is_dummy_video(url: str | None)` لتفحص:
  ```python
  def is_dummy_video(url: str | None) -> bool:
      if not url:
          return False
      u = str(url)
      return any(h in u for h in DUMMY_VIDEO_HASHES) or "/other/2026/10/10/" in u or "/other/2026/09/04/" in u
  ```

### الخطوة 2: محاكاة إصدار التطبيق الحديث في الهيدرز (Client Parity)
في [`app/core/client.py`](file:///c:/Users/HP/Documents/moviebox-fastapi/app/core/client.py):
عند تهيئة `MovieBoxHttpClient` أو في دالة الحقن:
* تحديث بيانات `CLIENT_INFO` لترسل الإصدار الأحدث المتوافق مع v4.0:
  * `version_code`: `50020126`
  * `version_name`: `"4.0.02"`
* إضافة الهيدر المخصص الجديد:
  * `X-M-Version`: `"4.0.02"`
* تحديث الـ `User-Agent`:
  * `com.community.oneroom/50020126 (Linux; U; Android 13; en_US; 2201117TY; Build/TQ2A.230405.003; Cronet/135.0.7012.3)`

---

## 3. مراجع ومعلومات إضافية مفيدة للآجنت القادم

1. **المستودع المرجعي لتحديثات البروتوكول:**  
   مستودع GitHub: [`solo12345689/moviebox-internal-api`](https://github.com/solo12345689/moviebox-internal-api)  
   (الفرع `main` و Tag `v4.0` يحتويان على أحدث التحديثات الخاصة ببروتوكول AOneRoom و v4.0.02).

2. **طريقة الاختبار السريع للآجنت:**
   ```bash
   python -c "import asyncio; from app.core.client import get_client; from moviebox_api.v3.urls import PLAY_INFO_PATH; asyncio.run(get_client().__aenter__())"
   ```
   عند إرسال المعاملات الصحيحة، يجب أن يعيد حقل `streams` كوكيز مشفرة `signCookie` تبدأ بـ `Edge-Cache-Cookie=urlprefix=...` بدلاً من رابط mp4 الوهمي.
