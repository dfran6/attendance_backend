"""Uniform error envelope: {statusCode, message, errorCode, details}.

Error codes are a stable contract with the frontend — add, don't rename.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("cds.errors")


class ErrorCode:
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    CSRF_FAILED = "CSRF_FAILED"
    ACCOUNT_PENDING = "ACCOUNT_PENDING"
    ACCOUNT_REJECTED = "ACCOUNT_REJECTED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    EMAIL_TAKEN = "EMAIL_TAKEN"
    STATE_CODE_TAKEN = "STATE_CODE_TAKEN"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    DUPLICATE_CHECKIN = "DUPLICATE_CHECKIN"
    CHALLENGE_EXPIRED = "CHALLENGE_EXPIRED"
    INVALID_CHALLENGE = "INVALID_CHALLENGE"
    SESSION_NOT_ACTIVE = "SESSION_NOT_ACTIVE"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    LOCATION_REQUIRED = "LOCATION_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_DEFAULT_CODES = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.VALIDATION_ERROR,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}


class AppError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def unauthorized(message: str = "Authentication required.", code: str = ErrorCode.UNAUTHORIZED) -> AppError:
    return AppError(401, code, message)


def forbidden(message: str = "You do not have permission to perform this action.", code: str = ErrorCode.FORBIDDEN) -> AppError:
    return AppError(403, code, message)


def not_found(resource: str = "Resource") -> AppError:
    return AppError(404, ErrorCode.NOT_FOUND, f"{resource} not found.")


def conflict(message: str, code: str = ErrorCode.CONFLICT, details: Optional[Dict[str, Any]] = None) -> AppError:
    return AppError(409, code, message, details)


def _body(status_code: int, error_code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"statusCode": status_code, "message": message, "errorCode": error_code, "details": details or {}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.status_code, exc.error_code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _DEFAULT_CODES.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(_body(exc.status_code, code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        fields: Dict[str, str] = {}
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
            msg = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
            fields[".".join(loc) or "_"] = msg
        return JSONResponse(
            _body(422, ErrorCode.VALIDATION_ERROR, "Some fields are invalid.", {"fields": fields}), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("unhandled_error", extra={"path": request.url.path})
        return JSONResponse(
            _body(500, ErrorCode.INTERNAL_ERROR, "Something went wrong. Please try again."), status_code=500
        )
