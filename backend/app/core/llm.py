import json

from openai import AsyncOpenAI

from app.core.config import settings


class LLMClient:
    """LLM 底层客户端，封装 OpenAI 兼容 API 的原始调用"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self.model = settings.LLM_MODEL

    async def chat(
        self,
        messages: list[dict], # 由LLMService封装
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        同步对话（非流式）

        Args:
            messages: 标准 OpenAI messages 格式
            temperature: 不传则用 API 默认值
            max_tokens: 不传则用 API 默认值

        Returns:
            LLM 生成的完整文本

        Raises:
            RuntimeError: 调用失败（含重试后仍失败）
        """
        kwargs: dict = {"model": self.model, "messages": messages}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            response = await self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {e}") from e

    async def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> dict:
        """
        同步对话（JSON 模式）

        Args:
            messages: 标准 OpenAI messages 格式（system prompt 需包含 JSON 指令）
            temperature: JSON 模式建议低温度以保证格式稳定
            max_tokens: 不传则用 API 默认值

        Returns:
            解析后的 dict

        Raises:
            RuntimeError: 调用失败或 JSON 解析失败
        """
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            response = await self.client.chat.completions.create(**kwargs)
            return json.loads(response.choices[0].message.content or "{}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM 返回非 JSON: {e}") from e
        except Exception as e:
            raise RuntimeError(f"LLM JSON 调用失败: {e}") from e

    async def chat_stream(self, messages: list[dict], temperature: float | None = None):
        """
        流式对话

        Args:
            messages: 标准 OpenAI messages 格式
            temperature: 不传则用 API 默认值

        Yields:
            str: 逐步生成的文本片段

        Raises:
            RuntimeError: 调用失败
        """
        try:
            kwargs: dict = {"model": self.model, "messages": messages, "stream": True}
            if temperature is not None:
                kwargs["temperature"] = temperature
            stream = await self.client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            raise RuntimeError(f"LLM 流式调用失败: {e}") from e
