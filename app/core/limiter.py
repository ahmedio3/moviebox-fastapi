"""SlowAPI rate limiter instance and exception handler."""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "status": "error",
            "error": "rate_limit_exceeded",
            "message": "تجاوزت الحد المسموح من الطلبات، حاول بعد دقيقة.",
        },
    )
