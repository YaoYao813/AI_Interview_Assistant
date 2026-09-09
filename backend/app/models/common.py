"""
通用响应模型
所有 API 遵循统一的响应格式：{success, code, message, data}
"""
from typing import Any, Optional
from pydantic import BaseModel


class ApiResponse(BaseModel):
    """统一 API 响应包装"""
    success: bool = True
    code: int = 200
    message: str = "ok"
    data: Optional[Any] = None

    @classmethod
    def ok(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        return cls(success=True, code=200, message=message, data=data)

    @classmethod
    def fail(cls, code: int, message: str, data: Any = None) -> "ApiResponse":
        return cls(success=False, code=code, message=message, data=data)
