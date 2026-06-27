<div align="center">

# 🎬 MovieBox FastAPI Backend

**Backend API powering the Watchera Android app — search, download links & subtitles from MovieBox**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688.svg)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![Deploy](https://img.shields.io/badge/Vercel-Deploy-black.svg)](https://vercel.com)

<br/>

A lightweight, stateless REST API that acts as a proxy/adapter between the **[Watchera Android app](https://github.com/ahmedio3/wacher)** and MovieBox's backend services. Handles search ranking, download link aggregation, subtitle extraction, and response normalization.

</div>

---

## 🚀 Live API

**Base URL:** `https://moviebox-fastapi.vercel.app`

| Endpoint | Rate Limit | Description |
|----------|------------|-------------|
| `GET /` | — | API info & available endpoints |
| `GET /health` | — | Health check |
| `GET /search` | 30/min | Search for movies & TV series |
| `GET /get_download_links` | 20/min | Get streaming URLs with embedded subtitles |
| `GET /get_subtitles` | 60/min | Get subtitle files (fallback endpoint) |

---

## 📡 API Reference

### `GET /search`

Search MovieBox's catalog with smart scoring and ranking.

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | `string` | ✅ | Movie or series name |
| `original_language` | `string` | ❌ | ISO 639-1 code (e.g., `en`, `ar`, `ja`, `ko`) |
| `limit` | `int` | ❌ | Max results (1–20, default: 8) |

**Example:**
```bash
curl "https://moviebox-fastapi.vercel.app/search?query=Inception&original_language=en&limit=5"
```

**Response:**
```json
{
  "status": "success",
  "query": "Inception",
  "total_results": 5,
  "results": [
    {
      "subject_id": "12345",
      "title": "Inception",
      "type": "movie",
      "poster": "https://...",
      "year": "2010",
      "rating": 8.8,
      "seasons": 0,
      "duration_seconds": 8880,
      "languages": ["english"],
      "country": "US",
      "description": "A thief who steals corporate secrets...",
      "genre": ["Action", "Sci-Fi", "Thriller"],
      "has_resource": true
    }
  ]
}
```

**Scoring Algorithm:**
- Original language match: **+100**
- Exact title match: **+50**
- Partial title match: **+20**
- Has available resource: **+10**
- Dubbed content penalty: **-200**

---

### `GET /get_download_links`

Fetch all download/streaming links for a movie or series with embedded subtitle information.

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject_id` | `string` | ✅ | MovieBox subject ID (from search results) |
| `resolution` | `int` | ❌ | Filter: `360`, `480`, `720`, or `1080` (default: all) |

**Example:**
```bash
curl "https://moviebox-fastapi.vercel.app/get_download_links?subject_id=12345&resolution=1080"
```

**Response:**
```json
{
  "status": "success",
  "subject_id": "12345",
  "total_links": 42,
  "seasons_found": [1, 2, 3],
  "episodes_per_season": {"1": 10, "2": 12, "3": 8},
  "resolutions_found": [360, 480, 720, 1080],
  "has_arabic_subtitles": true,
  "download_links": [
    {
      "url": "https://...",
      "resolution": 1080,
      "size": "1.2GB",
      "season": 1,
      "episode": 1,
      "resource_id": "abc123",
      "codec": "h264",
      "duration": 5400,
      "source_url": "https://...",
      "subtitles_available": true,
      "has_arabic_subtitle": true,
      "arabic_subtitle_url": "https://...",
      "all_subtitles": [
        {
          "language_code": "ar",
          "language_name": "Arabic",
          "url": "https://...",
          "size": 12345,
          "delay": 0
        }
      ],
      "total_languages": 3
    }
  ]
}
```

**Behavior:**
- Fetches all resolutions in parallel using `asyncio.gather`
- Deduplicates by (season, episode, resolution)
- Sorts by season ASC → episode ASC → resolution DESC
- Falls back to `/get_subtitles` per resource if embedded captions are empty

---

### `GET /get_subtitles`

Fallback endpoint to fetch subtitles for a specific video resource.

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject_id` | `string` | ✅ | MovieBox subject ID |
| `resource_id` | `string` | ✅ | Resource ID from download links |

**Example:**
```bash
curl "https://moviebox-fastapi.vercel.app/get_subtitles?subject_id=12345&resource_id=abc123"
```

**Response:**
```json
{
  "status": "success",
  "subject_id": "12345",
  "resource_id": "abc123",
  "has_arabic": true,
  "arabic_subtitle": {
    "language_code": "ar",
    "language_name": "Arabic",
    "url": "https://...",
    "size": 12345,
    "delay": 0
  },
  "all_subtitles": [...],
  "total_languages": 3
}
```

---

### `GET /health`

```json
{"status": "healthy", "service": "watchera-moviebox"}
```

---

## ⚡ Rate Limiting

All endpoints are protected by [slowapi](https://github.com/laurentS/slowapi) rate limiting, keyed by client IP:

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/search` | 30 requests | per minute |
| `/get_download_links` | 20 requests | per minute |
| `/get_subtitles` | 60 requests | per minute |

Exceeded limits return HTTP `429`:
```json
{
  "status": "error",
  "error": "rate_limit_exceeded",
  "message": "تجاوزت الحد المسموح من الطلبات، حاول بعد دقيقة."
}
```

---

## 🛠️ Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| **Framework** | FastAPI | 0.115.0 |
| **ASGI Server** | Uvicorn | 0.30.6 |
| **MovieBox SDK** | moviebox-api | ≥0.5.0 |
| **Rate Limiting** | slowapi | 0.1.9 |
| **Runtime** | Python | 3.12+ |
| **Deployment** | Vercel (Serverless) | — |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────┐
│          Watchera Android App            │
│    (Retrofit / OkHttp HTTP Client)       │
└─────────────────┬────────────────────────┘
                  │ HTTP GET
                  ▼
┌──────────────────────────────────────────┐
│       MovieBox FastAPI Backend           │
│                                          │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  │
│  │ Search  │  │ Download │  │Subtitle│  │
│  │Endpoint │  │ Links    │  │Endpoint│  │
│  └────┬────┘  └────┬─────┘  └───┬────┘  │
│       │            │            │        │
│  ┌────┴────────────┴────────────┴─────┐  │
│  │        moviebox-api (v3) SDK       │  │
│  │  • Search          • Subtitles    │  │
│  │  • VideoDetails    • HttpClient   │  │
│  └────────────────┬───────────────────┘  │
│                   │                      │
│  ┌────────────────┴───────────────────┐  │
│  │     Scoring & Normalization        │  │
│  │  • Language matching               │  │
│  │  • Dubbed content detection        │  │
│  │  • Deduplication                   │  │
│  │  • Response formatting             │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│         MovieBox Backend Servers         │
│     (api6.aoneroom.com, etc.)           │
└──────────────────────────────────────────┘
```

---

## 🚀 Deployment

### Vercel (Production)

The project is configured for automatic deployment on Vercel:

1. Push to `main` branch triggers automatic build & deploy
2. Vercel uses Python 3.12 runtime
3. Serverless functions handle each request

**Deploy manually:**
```bash
npm i -g vercel
vercel --prod
```

### Local Development

```bash
# Clone
git clone https://github.com/ahmedio3/moviebox-fastapi.git
cd moviebox-fastapi

# Install dependencies
pip install -r requirements.txt

# Run with hot reload
uvicorn main:app --reload --port 8000

# API docs (enabled locally)
open http://localhost:8000/docs
```

---

## 📂 Project Structure

```
moviebox-fastapi/
├── main.py              # Entire application (553 lines)
├── requirements.txt     # Python dependencies
├── vercel.json          # Vercel deployment config
└── README.md            # This file
```

---

## 🔗 Related Projects

| Project | Description |
|---------|-------------|
| **[wacher](https://github.com/ahmedio3/wacher)** | Watchera Android app (Kotlin + Jetpack Compose) |

---

## 📄 License

This project is for educational purposes. MovieBox content is sourced from third-party services.

---

<div align="center">

**Built with ❤️ using FastAPI & Python**

[Report Bug](https://github.com/ahmedio3/moviebox-fastapi/issues) · [Request Feature](https://github.com/ahmedio3/moviebox-fastapi/issues)

</div>
