"""Double-submit CSRF protection for cookie-authenticated browser requests.

The browser calls GET /api/v1/auth/csrf, which sets a `cds_csrf` cookie and returns the same
value in the body. Unsafe requests must echo it in the X-CSRF-Token header. Requests that
authenticate with an Authorization header (API clients, Swagger) carry no ambient
credentials and are exempt.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.core.exceptions import ErrorCode
from src.core.security import tokens_match

CSRF_COOKIE = "cds_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and not request.headers.get("authorization")
            and not tokens_match(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER))
        ):
            return JSONResponse(
                {
                    "statusCode": 403,
                    "message": "Your session security token is missing or stale. Please refresh and try again.",
                    "errorCode": ErrorCode.CSRF_FAILED,
                    "details": {},
                },
                status_code=403,
            )
        return await call_next(request)
