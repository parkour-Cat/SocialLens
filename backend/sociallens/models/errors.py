"""Error taxonomy shared by REST responses, task results and the extension."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    EXTENSION_OFFLINE = "extension_offline"
    NOT_LOGGED_IN = "not_logged_in"
    RATE_LIMITED = "rate_limited"
    CAPTCHA_REQUIRED = "captcha_required"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    UNSUPPORTED = "unsupported"
    UNKNOWN_PLATFORM = "unknown_platform"
    BAD_REQUEST = "bad_request"
    EXTENSION_ERROR = "extension_error"
    NOT_FOUND = "not_found"
    CURSOR_EXPIRED = "cursor_expired"
    INTERNAL = "internal"


HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.EXTENSION_OFFLINE: 503,
    ErrorCode.NOT_LOGGED_IN: 401,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.CAPTCHA_REQUIRED: 423,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.PARSE_ERROR: 502,
    ErrorCode.UNSUPPORTED: 404,
    ErrorCode.UNKNOWN_PLATFORM: 404,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.EXTENSION_ERROR: 502,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CURSOR_EXPIRED: 410,
    ErrorCode.INTERNAL: 500,
}


class SocialLensError(Exception):
    def __init__(self, code: ErrorCode | str, message: str = "", details: dict | None = None):
        self.code = ErrorCode(code) if code in ErrorCode.__members__.values() else ErrorCode.INTERNAL
        self.raw_code = str(code)
        self.message = message or self.code.value
        self.details = details or {}
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    def to_dict(self) -> dict:
        d = {"code": self.raw_code, "message": self.message}
        if self.details:
            d["details"] = self.details
        return d
