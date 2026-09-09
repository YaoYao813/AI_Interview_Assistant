"""
全局异常处理
类比 Spring Boot 的 @ControllerAdvice + 自定义 BusinessException
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

class AppException(Exception):
    """业务异常基类"""
    def __init__(self, message: str, status_code: int = 400, detail: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


class NotFoundException(AppException):
    """资源不存在"""
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, status_code=404)


class LLMException(AppException):
    """LLM 调用异常"""
    def __init__(self, message: str = "AI服务暂时不可用"):
        super().__init__(message, status_code=503)


class VectorStoreException(AppException):
    """向量库异常"""
    def __init__(self, message: str = "向量检索失败"):
        super().__init__(message, status_code=500)


class InvalidFileException(AppException):
    """文件校验异常"""
    def __init__(self, message: str = "文件格式不支持"):
        super().__init__(message, status_code=400)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "code": exc.status_code,
                "message": exc.message,
                "detail": exc.detail,
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理 Pydantic 参数校验失败"""
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
            })
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "code": 422,
                "message": "请求参数校验失败",
                "detail": {"errors": errors},
            }
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """兜底异常处理"""
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "code": 500,
                "message": "服务器内部错误",
                "detail": {"error": str(exc)},
            }
        )
