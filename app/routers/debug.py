"""Temporary diagnostics for the signed MovieBox client (removed after use)."""

import traceback

from fastapi import APIRouter, Query
from moviebox_api.v3.core import Homepage

from app.core.client import get_client
from app.services.extra_service import _get as web_get

router = APIRouter(tags=["Debug"])

DEBUG_KEY = "mbg-9f2c1a"


@router.get("/debug_signed")
async def debug_signed(key: str = Query("")):
    if key != DEBUG_KEY:
        return {"error": "forbidden"}

    out: dict = {}
    try:
        async with get_client() as client:
            out["token"] = bool(getattr(client, "_runtime_token", None))
            out["active_base"] = client.active_base

            try:
                homepage = Homepage(client_session=client)
                data = await homepage.get_content()
                out["home_ok"] = True
                out["home_items"] = len(data.get("items", []))
            except Exception as e:
                out["home_error"] = f"{type(e).__name__}: {e}"

            try:
                _, resp = await client.get(
                    "/wefeed-mobile-bff/tab-operating?page=1&tabId=0&version="
                )
                out["raw_status"] = resp.status_code
                out["raw_ct"] = resp.headers.get("content-type", "")
                out["raw_body"] = resp.text[:400]
            except Exception as e:
                out["raw_error"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        out["client_error"] = f"{type(e).__name__}: {e}"
        out["trace"] = traceback.format_exc()[-800:]

    try:
        web = await web_get("/wefeed-h5api-bff/home", {"page": 1})
        out["web_home_ok"] = True
        out["web_home_keys"] = list(web.keys())[:8]
    except Exception as e:
        out["web_home_error"] = f"{type(e).__name__}: {e}"

    return out
