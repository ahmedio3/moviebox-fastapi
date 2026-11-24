<div align="center">

# MovieBox FastAPI Backend

واجهة REST خفيفة تعمل كوسيط بين تطبيق **Watchera** لأندرويد وخدمات MovieBox.
توفّر البحث، تفاصيل المحتوى، الاكتشاف، روابط البث والتحميل، والترجمات.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688.svg)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![Deploy](https://img.shields.io/badge/Deploy-Vercel-black.svg)](https://vercel.com)

**Live API:** `https://moviebox-fastapi.vercel.app`

</div>

---

## نظرة عامة

- API بلا قاعدة بيانات؛ كل الطلبات تُجلب من خدمات MovieBox ثم تُعاد بصيغة موحّدة.
- يعتمد على مكتبة `moviebox-api` (الفرع v3) مع هوية عميل حديثة `v4.0.02`.
- روابط الوسائط موقّعة ومؤقتة، لذلك يجب طلب رابط جديد عند كل تشغيل أو تحميل.
- التخزين المؤقت داخل الذاكرة فقط (توكن المصادقة و`detailPath`)، وقد يختلف بين نسخ Vercel.
- لا توجد مصادقة على API نفسه؛ الحماية الوحيدة هي تحديد معدل الطلبات حسب IP.

---

## التشغيل المحلي

```bash
git clone https://github.com/ahmedio3/moviebox-fastapi.git
cd moviebox-fastapi

python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

ثم:

```text
http://localhost:8000/health
```

> `/docs` و`/redoc` معطّلان حالياً في `main.py` عبر `docs_url=None` و`redoc_url=None`.
> لتشغيلهما محلياً، احذف هذين المعاملين من إنشاء `FastAPI`.

يمكن أيضاً تشغيل:

```bash
python main.py
```

ويستخدم المنفذ `SERVER_PORT` أو `PORT` أو `P_SERVER_PORT` أو `10622` افتراضياً.

---

## نقاط النهاية

| الطريقة | المسار | الحد | الوصف |
|---|---|---|---|
| `GET` | `/` | — | معلومات API وقائمة المسارات |
| `GET` | `/health` | — | فحص الحالة |
| `GET` | `/search` | 30/دقيقة | البحث في كتالوج MovieBox |
| `GET` | `/item_details` | 30/دقيقة | تفاصيل فيلم أو مسلسل |
| `GET` | `/trending` | 15/دقيقة | المحتوى الرائج |
| `GET` | `/browse` | 15/دقيقة | تصفّح مع فلاتر |
| `GET` | `/random` | 15/دقيقة | محتوى عشوائي |
| `GET` | `/get_download_links` | 30/دقيقة | روابط البث/التحميل مع الترجمات |
| `GET` | `/get_stream` | 30/دقيقة | رابط بث DASH/MP4 مع الهيدرز المطلوبة |
| `GET` | `/get_subtitles` | 60/دقيقة | ترجمات عبر `resource_id` |
| `GET` | `/adult` | 10/دقيقة | محتوى +18 بكلمات مفتاحية |
| `GET` | `/adult_keywords` | — | قائمة كلمات +18 المتاحة |

---

## مرجع API

### `GET /search`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `query` | `string` | ✅ | اسم الفيلم أو المسلسل |
| `original_language` | `string` | ❌ | كود لغة مثل `en`, `ar`, `ja`, `ko` |
| `limit` | `int` | ❌ | عدد النتائج، من 1 إلى 20 (افتراضي 8) |

```bash
curl "https://moviebox-fastapi.vercel.app/search?query=Obsession&limit=1"
```

استجابة حقيقية مختصرة:

```json
{
  "status": "success",
  "query": "Obsession",
  "total_results": 1,
  "results": [
    {
      "subject_id": "1732378050823619144",
      "title": "Obsession",
      "type": "movie",
      "poster": "https://pbcdn.aoneroom.com/image/...",
      "year": "2026",
      "rating": 7.8,
      "seasons": 0,
      "duration_seconds": 6540,
      "languages": ["English"],
      "country": "United States",
      "description": "",
      "genre": ["Fantasy", "Horror", "Thriller"],
      "has_resource": true
    }
  ]
}
```

**ترتيب النتائج:**

- تطابق اللغة الأصلية: `+100`
- تطابق العنوان الكامل: `+50`
- تطابق جزئي للعنوان: `+20`
- وجود مصدر قابل للتشغيل: `+10`
- محتوى مدبلج: `-200`

`total_results` هو عدد النتائج المعادة بعد تطبيق `limit`، وليس إجمالي الكتالوج.

---

### `GET /item_details`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `subject_id` | `string` | ✅ | معرّف المحتوى من البحث |
| `include_seasons` | `bool` | ❌ | إضافة تفاصيل المواسم (افتراضي `false`) |

```bash
curl "https://moviebox-fastapi.vercel.app/item_details?subject_id=1732378050823619144"
```

الحقول الأساسية داخل `item`: `subject_id`, `title`, `description`, `poster`, `rating`, `year`, `type`, `languages`, `country`, `genre`, `seasons_count`, `duration_seconds`, `has_resource`.

مع `include_seasons=true` يُضاف كائن `seasons` كما يعيده MovieBox (قائمة المواسم وعدد الحلقات والجودات المتاحة).

---

### `GET /trending`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `tab` | `string` | ❌ | `all`, `movie`, `tv`, `anime` |
| `page` | `int` | ❌ | رقم الصفحة (افتراضي 1) |
| `safe_mode` | `bool` | ❌ | استبعاد المحتوى غير اللائق (افتراضي `true`) |
| `limit` | `int` | ❌ | من 1 إلى 50 (افتراضي 20) |

```bash
curl "https://moviebox-fastapi.vercel.app/trending?tab=movie&limit=2"
```

---

### `GET /browse`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `genre` | `string` | ❌ | نوع أو أكثر مفصولة بفاصلة، مثل `action,drama` |
| `type` | `string` | ❌ | `movie`, `series`, `all` |
| `sort` | `string` | ❌ | `rating`, `newest`, `oldest`, `random` |
| `safe_mode` | `bool` | ❌ | استبعاد المحتوى غير اللائق |
| `limit` | `int` | ❌ | من 1 إلى 50 (افتراضي 20) |

> `/browse` لا يقرأ كتالوجاً كاملاً؛ بل ينفّذ عدة عمليات بحث بكلمات مفتاحية ثم يفلتر ويرتّب النتائج. عند عدم تمرير `genre` يستخدم كلمات مثل `popular`, `action`, `drama`, `top`.

---

### `GET /random`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `type` | `string` | ❌ | `movie`, `series`, `all` |
| `safe_mode` | `bool` | ❌ | استبعاد المحتوى غير اللائق |
| `limit` | `int` | ❌ | من 1 إلى 10 (افتراضي 1) |

نتائج `/trending` و`/browse` و`/random` تستخدم نفس حقول عنصر البحث:
`subject_id`, `title`, `type`, `poster`, `year`, `rating`, `seasons`, `duration_seconds`, `languages`, `country`, `description`, `genre`, `has_resource`.

---

### `GET /get_download_links`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `subject_id` | `string` | ✅ | معرّف المحتوى |
| `resolution` | `int` | ❌ | `360`, `480`, `720`, `1080` — بدونها تُعاد كل الجودات |
| `season` | `int` | ❌ | رقم الموسم (0 للأفلام) |
| `episode` | `int` | ❌ | رقم الحلقة (0 للأفلام) |
| `page` | `int` | ❌ | رقم صفحة الحلقات عند عدم تحديد حلقة (افتراضي 1) |
| `limit` | `int` | ❌ | عدد الحلقات في الصفحة، من 1 إلى 50 (افتراضي 10) |

أمثلة:

```bash
# فيلم
curl "https://moviebox-fastapi.vercel.app/get_download_links?subject_id=1732378050823619144"

# حلقة محددة
curl "https://moviebox-fastapi.vercel.app/get_download_links?subject_id=123548964812640048&season=1&episode=1"

# شريحة حلقات
curl "https://moviebox-fastapi.vercel.app/get_download_links?subject_id=123548964812640048&season=1&page=1&limit=10"
```

أهم الحقول في الاستجابة:

- `total_links`, `current_page`, `limit`, `has_more`
- `seasons_found`, `episodes_per_season`, `resolutions_found`
- `has_arabic_subtitles`
- `download_links[]`: كل عنصر يحتوي `url`, `resolution`, `size`, `season`, `episode`, `resource_id`, `codec`, `duration`, `stream_type`, `cookie`, `headers`, `resolutions_available`, وحقول الترجمة.

مثال لهيدرز رابط DASH:

```json
{
  "cookie": "",
  "headers": {
    "User-Agent": "Mozilla/5.0 ...",
    "Referer": "https://movie-box.co/movies/...",
    "X-MB-Token": "<signed-token>"
  }
}
```

السلوك الفعلي:

- يحل روابط البث لكل حلقة عبر `resolve_stream_for_episode`.
- يدمج ترجمات `extCaptions` المرفقة، ويلجأ إلى `resource_id` عند الحاجة.
- يزيل التكرار ويرتّب حسب الموسم ثم الحلقة ثم الدقة تنازلياً.
- قد يعيد رابط MP4 كبديل إذا لم يتوفر DASH.
- إذا لم تتوفر الجودة المطلوبة، يعيد أول جودة متاحة بدلاً منها.
- يستبعد أي رابط وهمي معروف.

---

### `GET /get_stream`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `subject_id` | `string` | ✅ | معرّف المحتوى |
| `season` | `int` | ❌ | رقم الموسم (0 للأفلام) |
| `episode` | `int` | ❌ | رقم الحلقة (0 للأفلام) |

```bash
curl "https://moviebox-fastapi.vercel.app/get_stream?subject_id=1732378050823619144&season=0&episode=0"
```

استجابة حقيقية مختصرة:

```json
{
  "status": "success",
  "subject_id": "1732378050823619144",
  "season": 0,
  "episode": 0,
  "stream_url": "https://sbcdnw.hakunaymatata.com/dash/1732378050823619144_0_0_1080_h265_405/index_web.mpd",
  "stream_type": "dash",
  "cookie": "",
  "headers": {
    "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 ...",
    "Referer": "https://movie-box.co/movies/obsession-YCQTo4djY32?id=1732378050823619144&type=/movie/detail&detailSe=0&detailEp=0&lang=en",
    "X-MB-Token": "<signed-token>"
  },
  "resolutions": [1080, 720, 480],
  "codec": "hevc",
  "duration": 6533,
  "size": 2912846918
}
```

**مهم للتشغيل والتحميل:**

- مرّر `headers` كما هي إلى ExoPlayer أو محمّل التحميل.
- لا ترسل هيدر `Cookie`؛ مصادقة CDN تعتمد على `X-MB-Token`.
- `Referer` إلزامي أيضاً لروابط MP4، وليس فقط لـ DASH.
- في مسار `web play` يكون الحقل `cookie` فارغاً عمداً، وهو موجود للتوافق مع الإصدارات القديمة من التطبيق.
- لا تخزّن `stream_url` طويلاً؛ التوقيع مؤقت. اطلب رابطاً جديداً عند كل تشغيل.

---

### `GET /get_subtitles`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `subject_id` | `string` | ✅ | معرّف المحتوى |
| `resource_id` | `string` | ✅ | من حقل `resource_id` في روابط التحميل |

```bash
curl "https://moviebox-fastapi.vercel.app/get_subtitles?subject_id=1732378050823619144&resource_id=7088654235860363648"
```

الحقول: `status`, `subject_id`, `resource_id`, `has_arabic`, `arabic_subtitle`, `all_subtitles`, `total_languages`.

كل ترجمة تحتوي: `language_code`, `language_name`, `url`, `size`, `delay`.

---

### `GET /adult`

| المعامل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `type` | `string` | ❌ | `movie`, `series`, `all` |
| `queries` | `string` | ❌ | كلمات مفتاحية مفصولة بفاصلة (حد أقصى 10) |
| `limit` | `int` | ❌ | من 1 إلى 60 (افتراضي 10) |
| `sort` | `string` | ❌ | `random`, `rating`, `newest` |

- عند عدم تمرير `queries` يستخدم أول 5 كلمات من قائمة `ADULT_QUERIES`.
- ينفّذ البحث بالكلمات بالتوازي، ويضيف نتائج تبويب الأنمي التي تطابق الفلتر.
- الاستجابة بنفس صيغة عنصر البحث.

### `GET /adult_keywords`

يعيد قائمة الكلمات المفتاحية الكاملة المتاحة لقسم +18:

```json
{
  "status": "success",
  "keywords": ["..."],
  "total": 118
}
```

---

### `GET /` و`GET /health`

```json
{
  "status": "healthy",
  "service": "watchera-moviebox"
}
```

`/` يعيد اسم الخدمة وقائمة المسارات والحدود كما هي مسجّلة داخل التطبيق.

---

## الأخطاء وتحديد المعدل

كل الأخطاء تُعاد بصيغة FastAPI:

```json
{
  "detail": "رسالة الخطأ"
}
```

عند تجاوز الحد:

```json
{
  "status": "error",
  "error": "rate_limit_exceeded",
  "message": "تجاوزت الحد المسموح من الطلبات، حاول بعد دقيقة."
}
```

الحالة `429` تعني تجاوز الحد، و`404` تعني عدم توفر المحتوى أو الرابط، و`500` تعني فشلاً من المصدر أو خطأ غير متوقع.

---

## المشكلة المعروفة: الفيديو الوهمي وفشل التشغيل

### الأعراض

- `/get_stream` يعيد فيديو مدته حوالي **23 ثانية** أو حجماً صغيراً جداً.
- الرابط قد يكون MP4 تحذيرياً يطلب «تحديث التطبيق».
- أو يعيد `index.mpd`/`index_web.mpd` لكن الطلب عليه أو على أول Segment يعيد `403` أو `429`.
- التطبيق يفتح المشغّل ثم يتوقف، أو يفشل التحميل.

### السبب

1. MovieBox بدأ في **سبتمبر/أكتوبر 2026** بإرجاع مقطع تحذيري وهمي للعملاء القديمين.
2. مكتبة `moviebox-api` القديمة كانت ترسل هوية إصدار قديمة ولا ترسل `X-M-Version`.
3. تم تحديث الهوية في `app/core/client.py` إلى `v4.0.02` و`version_code=50020126` وإضافة `X-M-Version`.
4. رغم ذلك، بقي `play-info` الأصلي يعيد المقطع الوهمي لبعض العناوين، لذلك أُضيف fallback إلى web player:
   - `GET /wefeed-h5api-bff/subject/play`
   - مع `detailPath` و`se` و`ep` و`streamSignType=1`.
5. المشكلة الثانية كانت في بناء رابط DASH والهيدرز:
   - كان الكود يبني `index.mpd` بدلاً من `index_web.mpd` القادم من `dash[0].url`.
   - كان يرسل `signCookie` كـ `Cookie`، بينما CDN يتوقع `X-MB-Token` (أو قيمة `signHeaderKey`).
   - كان `Referer` ناقصاً، وهو مطلوب لـ DASH وMP4.

### الإصلاح الحالي

- استخدام `dash[0].url` الفعلي، وغالباً ينتهي بـ `index_web.mpd`.
- إرسال `signCookie` كما هو في هيدر `X-MB-Token`.
- إضافة `Referer` بالصيغة:

```text
https://movie-box.co/movies/<detailPath>?id=<subjectId>&type=/movie/detail&detailSe=<season>&detailEp=<episode>&lang=en
```

- إبقاء `cookie` فارغاً في استجابة web fallback.
- استبعاد أي رابط يحتوي هاش أو مسار الفيديو الوهمي عبر `is_dummy_video`.

### إذا تكررت المشكلة مستقبلاً

1. **تحقق من وجود الفيديو الوهمي:**
   - شغّل `/get_stream` على عنوان معروف.
   - إذا كانت `duration` حوالي 23 أو `size` صغيراً جداً، أو ظهر مسار `/other/2026/...`، فالطلب يُعامل كعميل قديم.

2. **أضف الهاش أو المسار الجديد:**
   - في `app/config.py` أضف الهاش إلى `DUMMY_VIDEO_HASHES` والمسار إلى `DUMMY_VIDEO_PATH_MARKERS`.
   - `is_dummy_video` في `app/utils/helpers.py` سيستبعده تلقائياً.

3. **تحقق من هوية العميل:**
   - `APP_VERSION_NAME` و`APP_VERSION_CODE` و`X-M-Version` في `app/core/client.py`.
   - حدّثها إذا أعلنت MovieBox إصداراً أحدث.

4. **اختبر web play مباشرة:**
   - تأكد أن الاستجابة تحتوي `dash` و`signCookie` غير فارغ.
   - تحقق من `signHeaderKey`؛ القيمة الافتراضية `X-MB-Token`.

5. **اختبر MPD وأول Segment:**
   - يجب أن يعيد MPD الحالة `200`.
   - استخدم نفس `headers` لطلب `init-stream0.m4s` و`chunk-stream0-00001.m4s`.
   - إذا أعاد `403/429`: راجع `X-MB-Token` و`Referer`، وتأكد من عدم إرسال `Cookie`.

6. **تحقق من الرابط:**
   - استخدم `dash[0].url` ولا تبنِ `index.mpd` يدوياً.
   - تأكد أن الرابط لا يحتوي على هاش وهمي.

7. **بعد الإصلاح:**
   - اختبر فيلماً وحلقة مسلسل (مثلاً Obsession وBleach S1E1).
   - تأكد أن MPD وأول Segment يعيدان `200`.
   - ارفع التعديل إلى `main` وأعد نشر Vercel.

### اختبار سريع

```python
import httpx

BASE = "https://moviebox-fastapi.vercel.app"
info = httpx.get(
    f"{BASE}/get_stream",
    params={"subject_id": "1732378050823619144", "season": 0, "episode": 0},
    timeout=60,
).json()

print(info["stream_url"])
print(sorted(info["headers"]))

media = httpx.get(info["stream_url"], headers=info["headers"], timeout=60)
print("MEDIA:", media.status_code, len(media.content))
```

يجب أن تكون النتيجة `MEDIA: 200` مع وجود `X-MB-Token` و`Referer` داخل الهيدرز.

---

## بنية المشروع

```text
moviebox-fastapi/
├── main.py                     # إنشاء FastAPI وتسجيل الراوترات
├── requirements.txt            # الاعتماديات
├── .python-version             # Python 3.12
├── app/
│   ├── config.py               # الثوابت، اللغات، الفلاتر، هاشات الفيديو الوهمي
│   ├── core/
│   │   ├── client.py           # هوية عميل MovieBox وإدارة التوكن
│   │   └── limiter.py          # slowapi ومعالج 429
│   ├── routers/
│   │   ├── search.py           # /search و/item_details
│   │   ├── discover.py         # /trending و/browse و/random
│   │   ├── media.py            # /get_download_links و/get_stream و/get_subtitles
│   │   ├── adult.py            # /adult و/adult_keywords
│   │   └── system.py           # / و/health
│   ├── services/
│   │   ├── download_service.py # تجميع صفحات التحميل
│   │   └── stream_service.py   # DASH، web play fallback، الهيدرز
│   └── utils/
│       ├── formatters.py       # توحيد صيغة الاستجابات
│       └── helpers.py          # فحص المحتوى والترجمات والفيديو الوهمي
└── README.md
```

---

## التقنيات

| المكوّن | التقنية |
|---|---|
| Framework | FastAPI `0.115.0` |
| ASGI Server | Uvicorn `0.30.6` |
| MovieBox SDK | `moviebox-api` (v3، من GitHub) |
| Rate Limiting | slowapi `0.1.9` |
| Runtime | Python `3.12` |
| Deployment | Vercel |

---

## ملاحظات وحدود

- الخدمة تعتمد على واجهات MovieBox غير الرسمية؛ أي تغيير في بروتوكولها قد يوقف روابط البث.
- لا توجد قاعدة بيانات أو حسابات مستخدمين.
- التخزين المؤقت في الذاكرة قد لا يكون مشتركاً بين كل نسخ Vercel.
- الروابط الموقّعة قصيرة العمر، وأي `403/429` غالباً يعني توقيعاً منتهياً أو هيدراً خاطئاً.
- لا توجد اختبارات آلية في المستودع حالياً؛ الاعتماد على اختبارات smoke اليدوية الموضحة أعلاه.
- المشروع لأغراض تعليمية، والمحتوى مملوك لخدمات الطرف الثالث.

---

## مشاريع مرتبطة

| المشروع | الوصف |
|---|---|
| [wacher](https://github.com/ahmedio3/wacher) | تطبيق Watchera لأندرويد (Kotlin + Jetpack Compose) |

---

<div align="center">

**Built with FastAPI & Python**

[Report Bug](https://github.com/ahmedio3/moviebox-fastapi/issues) · [Request Feature](https://github.com/ahmedio3/moviebox-fastapi/issues)

</div>
