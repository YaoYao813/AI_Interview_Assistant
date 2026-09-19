"""SSE（Server-Sent Events）事件序列化

统一流式接口的事件格式，各模块共用同一套 schema：

    data: {"type": "<事件类型>", "data": <载荷>}\n\n

事件类型（type）约定：
    token / sources      文本与引用（RAG、简历追问）
    score/feedback/model_answer   面试评价的分段内容
    done                 流结束，data 可携带最终结构化结果
    error                流中途出错
"""
import json


def sse_event(event_type: str, data=None) -> str:
    """构造一条 SSE 事件文本

    Args:
        event_type: 事件类型
        data: 载荷；为 None 时输出中省略 data 字段

    Returns:
        可直接写入 StreamingResponse 的字符串
    """
    payload: dict = {"type": event_type}
    if data is not None:
        payload["data"] = data
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
