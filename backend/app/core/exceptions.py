"""统一错误模型与异常处理器。响应结构：{code, message, detail}。"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """业务异常：携带 HTTP 状态码 + 错误码 + 给用户的消息。"""

    def __init__(self, message: str, code: str = "BAD_REQUEST", status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在", code: str = "NOT_FOUND"):
        super().__init__(message, code=code, status_code=404)


class ForbiddenError(AppError):
    def __init__(self, message: str = "无权限访问", code: str = "FORBIDDEN"):
        super().__init__(message, code=code, status_code=403)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "未认证或凭证失效", code: str = "UNAUTHORIZED"):
        super().__init__(message, code=code, status_code=401)


class ProviderError(AppError):
    """模型 Provider 调用失败（上游 4xx/5xx/网络错误/维度不符等）。"""

    def __init__(
        self,
        message: str,
        code: str = "PROVIDER_ERROR",
        status_code: int = 502,
        provider_status: int | None = None,
        detail: str | None = None,
    ):
        super().__init__(message, code=code, status_code=status_code)
        self.provider_status = provider_status  # 上游 HTTP 状态码（仅信息用）
        self.detail = detail  # 上游原始错误 message


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "detail": None},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "detail": None,
            },
        )
