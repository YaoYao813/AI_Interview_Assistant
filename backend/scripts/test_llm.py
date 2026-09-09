"""LLM 快速测试脚本 —— 验证模型连通性"""
import asyncio

from app.services.llm_service import get_llm_service

async def main():
    llm = get_llm_service()
    print(f"模型: {llm.model_name}  |  窗口: {llm.max_context_tokens}\n")

    reply = await llm.chat(
        system_prompt="你是AI助手，用中文回答，简洁。",
        user_message="什么是FastAPI？一句话概括。",
    )
    print(f"回复: {reply}")
    print(f"token: {llm.count_tokens(reply)}")

if __name__ == "__main__":
    asyncio.run(main())
