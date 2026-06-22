# MovieBox FastAPI Backend for Watchera

Backend API للبحث وجلب روابط التحميل والترجمات من MovieBox.

## Endpoints

- `GET /search?query=TITLE&original_language=en&limit=8` — بحث
- `GET /get_download_links?subject_id=ID` — كل روابط التحميل (مع الترجمات المضمنة)
- `GET /get_download_links?subject_id=ID&resolution=1080` — جودة محددة
- `GET /get_subtitles?subject_id=ID&resource_id=RID` — ترجمات (fallback)
- `GET /health` — فحص الصحة

## Response Contract (متوافق مع `MovieBoxApiImpl` في تطبيق Android)

### Search result
```json
{
  "subject_id": "...",
  "title": "...",
  "type": "movie" | "series",
  "poster": "https://...",
  "year": "2024",
  "rating": 7.5,
  "seasons": 0,
  "duration_seconds": 5400,
  "languages": ["english"],
  "country": "US",
  "description": "...",
  "genre": ["Action"],
  "has_resource": true
}
```

### Download link (per file)
```json
{
  "url": "https://...",
  "resolution": 1080,
  "size": "1.2GB",
  "season": 1,
  "episode": 1,
  "resource_id": "...",
  "codec": "h264",
  "duration": 5400,
  "source_url": "https://...",
  "subtitles_available": true,
  "has_arabic_subtitle": true,
  "arabic_subtitle_url": "https://...",
  "all_subtitles": [
    {"language_code": "ar", "language_name": "Arabic", "url": "...", "size": 12345, "delay": 0}
  ],
  "total_languages": 3
}
```

## Rate Limits

- `/search`: 30/minute
- `/get_download_links`: 20/minute
- `/get_subtitles`: 60/minute

## Local Development

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
