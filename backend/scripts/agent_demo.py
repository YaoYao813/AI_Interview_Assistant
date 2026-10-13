import asyncio
import json

from openai import AsyncOpenAI
from app.core.config import settings

client = AsyncOpenAI(
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL
)
model = settings.LLM_MODEL
MAX_STEPS = 5

#工具 schema
TOOLS = [
    {
        "type":"function",
        "function":{
            "name":"get_weather",
            "description":"用于查询某个城市的天气时调用。",
            "parameters":{
                "type":"object",
                "properties":{
                    "city":{"type":"string","description":"城市名，如 深圳"}
                },
                "required":["city"],
            },
        },
    },
# 第二个工具：除法计算，故意设计除数为0时报错，验证异常处理
    {
        "type": "function",
        "function": {
            "name": "divide",
            "description": "计算两个数字的除法商值。",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "被除数"},
                    "b": {"type": "number", "description": "除数"}
                },
                "required": ["a","b"],
            },
        },
    }
]

#工具实现
def get_weather(city:str)->str:
    if city == "火星":
        raise ValueError("未知城市，查询失败！")
    return f"{city}今天天气晴，气温25-29摄氏度！"

def divide(a,b):
    if b == 0:
        raise ZeroDivisionError("除数不能为 0")
    return f"计算结果：{a} ÷ {b} = {a / b:.2f}"

TOOL_IMPL = {
    "get_weather": get_weather,
    "divide": divide
}

async def run(question: str) -> str:
    messages = [
        {"role":"system","content":"你可以调用工具来回答问题。"},
        {"role":"user","content":question}
    ]

    for step in range(MAX_STEPS):
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message # 模型返回的助理消息 里面包含tool_calls
        print(f"[step {step}] finish_reason={resp.choices[0].finish_reason}")

        if msg.tool_calls:
            # 关键：把这条 assistant 消息（含 tool_calls）原样塞回 history
            messages.append(msg)  # SDK 不认就换成 msg.model_dump(exclude_none=True)

            for tc in msg.tool_calls:
                name = tc.function.name
                # ★字段②.5：arguments 是【JSON 字符串】，不是对象；而且可能非法
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = None
                    result = "参数不是合法 JSON，请重新调用"
                else:
                    try:
                        result = TOOL_IMPL[name](**args)
                    except Exception as e:
                        result = f"工具执行失败：{e}"  # ← 错误【当结果喂回去】，不是抛出去

                # ============ ★字段③：把结果用匹配的 tool_call_id 回填 ============
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,  # ← 必须和上面 tc.id 一模一样，否则 400
                    "content": str(result),
                })

            continue  # 继续下一轮，让模型读工具结果

            # 没有 tool_calls → 这轮是最终答案
        return msg.content or ""

        return "超过最大步数，强制停止"

if __name__ == "__main__":
    # 测试用例1：正常工具调用闭环
    # print(asyncio.run(run("北京天气怎么样？")))

    # 测试用例2：工具抛出异常场景
    # print(asyncio.run(run("火星的天气怎么样？")))

    # 测试用例3：第二个工具正常调用
    # print(asyncio.run(run("100除以7等于多少？")))

    # 测试用例4：第二个工具触发报错
    print(asyncio.run(run("10除以0等于多少？")))

