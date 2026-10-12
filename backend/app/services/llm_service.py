from app.core.config import settings
from app.core.llm import LLMClient


class LLMService:
    """LLM 调用统一封装，所有业务模块通过此类调用 LLM"""

    def __init__(self):
        self.client = LLMClient()
        self.model = settings.LLM_MODEL
        self._max_tokens = settings.LLM_MAX_TOKENS
        self._temperature = settings.LLM_TEMPERATURE

        # tokenizer 用于 count_tokens 估算，加载失败不影响核心功能
        self._tokenizer = None
        try:
            import tiktoken
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            pass

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        同步对话（非流式）

        Args:
            system_prompt: 系统提示词（定义角色、规则）
            user_message: 用户消息
            temperature: 不传则用 settings.LLM_TEMPERATURE 默认值
            max_tokens: 不传则用 settings.LLM_MAX_TOKENS 默认值

        Returns:
            LLM 生成的完整文本

        Raises:
            RuntimeError: 调用失败（含重试后仍失败）
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return await self.client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """带工具的对话（阶段 3.1）。

        与 chat() 的两个区别：
          1. 入参是【完整 messages】，而不是 (system_prompt, user_message)——
             工具循环需要把 assistant(含 tool_calls) / tool 结果一条条往里塞。
          2. 返回【整条 assistant message】，而不是只回 content——调用方要靠
             .tool_calls 决定下一步执行什么。

        为什么新开方法而不改 chat()：chat() 有 4 个调用点，它们都不需要知道工具；
        改签名会把「工具调用」这个概念泄漏到整条业务链。旧 chat() 签名与实现均不动。
        """
        return await self.client.chat_with_tools(
            messages,
            tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> dict:
        """
        同步对话（JSON 模式，强制返回 JSON）

        Args:
            system_prompt: 系统提示词（会自动追加 JSON 格式要求）
            user_message: 用户消息
            temperature: JSON 模式建议低温度（默认 0.3），保证格式稳定
            max_tokens: 不传则用 API 默认值

        Returns:
            解析后的 dict

        Raises:
            RuntimeError: 调用失败或 LLM 返回非 JSON
        """
        json_system = system_prompt + "\n请严格以 JSON 格式返回结果，不要包含其他文字。"
        messages = [
            {"role": "system", "content": json_system},
            {"role": "user", "content": user_message},
        ]
        return await self.client.chat_json(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def chat_stream(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
    ):
        """
        流式对话（逐 token 返回，适合 SSE 推送）

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            temperature: 不传则用 API 默认值

        Yields:
            str: 逐步生成的文本片段

        Raises:
            RuntimeError: 调用失败
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        async for chunk in self.client.chat_stream(messages, temperature=temperature):
            yield chunk

    # ========== 辅助方法 ==========
    def count_tokens(self, text: str) -> int:
        """
        估算 Token 数量（用于控制上下文长度）
        注意：这是估算值，实际消耗以 API 返回为准
        """
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        # 兜底：中文约 1.5 字符/token，英文约 4 字符/token
        return len(text) // 2

    def count_messages_tokens(self, messages: list[dict]) -> int:
        """估算多轮对话总 Token 数"""
        total = 0
        for msg in messages:
            total += self.count_tokens(str(msg.get("content", "")))
            total += 4  # 每条消息的角色标记约 4 token
        return total

    # ========== 查询属性 ==========
    @property
    def model_name(self) -> str:
        return self.model

    @property
    def max_context_tokens(self) -> int:
        """当前模型的最大上下文窗口。

        厂商 /models 只返回模型 id，不给窗口大小，所以这张表是**人工维护**的：
        换模型必须一起改。未登记的模型会静默落到兜底值 16385——那是个错值，
        真要拿它做上下文截断之前，先把表补全。
        """
        context_map = {
            "deepseek-flash": 65536,
            "deepseek-v4-pro": 65536,
            "deepseek-chat": 65536,   # 未列出的兼容别名，实际路由到 deepseek-flash
            "deepseek-v3": 65536,
        }
        return context_map.get(self.model, 16385)

# ===== 全局单例 =====
_llm_service_instance: LLMService | None = None

def get_llm_service() -> LLMService:
    """获取 LLMService 单例"""
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = LLMService()
    return _llm_service_instance

def reset_llm_service() -> None:
    """重置单例（测试用）"""
    global _llm_service_instance
    _llm_service_instance = None