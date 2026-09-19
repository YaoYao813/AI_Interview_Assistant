import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from app.core.config import settings
from app.infrastructure.document_loader import load
from app.services.llm_service import get_llm_service, LLMService
from app.utils.sse import sse_event

logger = logging.getLogger(__name__)


# ========== Prompt 模板 ==========
RESUME_ANALYSIS_SYSTEM_PROMPT = """你是一位拥有 10 年经验的资深技术招聘专家，曾在字节跳动、阿里巴巴担任技术面试官。
你擅长从简历中挖掘候选人的真实技术能力、项目亮点和潜在不足。
## 你的任务
分析以下简历文本，生成一份结构化的分析报告。
## 分析要求
1. **简历概况**：总结候选人的经验年限、学历背景、核心技术栈
2. **优势亮点**：列出 3~5 个具体优势，每个优势必须附上简历中的具体证据
3. **不足之处**：列出 3~5 个不足之处，每个不足必须给出具体改进建议
4. **岗位匹配**：推荐 3 个适合的技术岗位，每个岗位给出匹配度评分（百分制）和推荐理由
## 输出格式约束（非常重要）
你必须**严格**按照以下 JSON 格式输出，不要输出任何其他内容，不要加 markdown 代码块标记：
{
  "overview": {
    "years_of_experience": "X年",
    "education": "学历和专业",
    "core_tech_stack": ["技术1", "技术2", "技术3"],
    "current_role": "当前职位"
  },
  "strengths": [
    {
      "point": "优势描述",
      "evidence": "简历中的具体证据",
      "impact": "这个优势在面试中的价值"
    }
  ],
  "weaknesses": [
    {
      "point": "不足之处",
      "reason": "为什么这是个问题",
      "suggestion": "具体改进建议"
    }
  ],
  "job_matches": [
    {
      "role": "推荐岗位",
      "score": 85,
      "reason": "匹配理由",
      "gap_skills": ["需要补充的技能1", "需要补充的技能2"]
    }
  ],
  "summary": "综合评价（100字以内）"
}
## 注意事项
- 如果简历中某些维度信息不足，请如实标注"信息不足"
- 评价要客观、具体，避免空泛的夸奖或批评
- 从面试官视角出发，思考"这份简历在面试中会被问到什么问题"
- 如果简历包含多个项目经历，重点分析最近 2~3 个项目"""


RESUME_CHAT_SYSTEM_PROMPT = """你是一位拥有 10 年经验的资深技术招聘专家，曾在字节跳动、阿里巴巴担任技术面试官。

## 你的角色
你正在和一位求职者对话，帮助他/她优化简历、提升面试竞争力。

## 参考信息
**简历原文：**
{resume_text}

**AI 分析报告：**
{analysis_summary}

## 对话要求
1. 基于上述简历和分析报告，针对用户的问题给出具体、可操作的建议
2. 回答要结合简历中的具体项目经历、技能点，不要泛泛而谈
3. 如果用户问如何改写某段经历，请给出具体的改写示例
4. 如果用户问面试准备，请从面试官视角给出高频问题和回答思路
5. 回答简洁有条理，适合求职场景

## 对话历史
{history}

## 用户问题
{message}

## 回答"""
def _safe_parse_json(text: str) -> dict:
    """
    安全解析 LLM 返回的 JSON（容错处理）
    容错策略（按优先级尝试）：
      1. 直接解析整个文本（理想情况）
      2. 提取 ```json ... ``` 代码块内容
      3. 提取第一个 { 到最后一个 } 之间的内容
      4. 尝试修复截断的 JSON（补全缺失的 }]
      5. 都失败则返回错误信息
    Args:
        text: LLM 返回的原始文本
    Returns:
        解析后的 dict，至少包含 {"error": "解析失败说明"}
    """
    if not text or not text.strip():
        return {"error": "解析失败", "message": "AI 返回内容为空"}
    text = text.strip()
    # 策略 1：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 策略 2：提取代码块
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 策略 3：提取最外层 JSON
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = text[start_idx:end_idx + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    # 策略 4：尝试补全截断的 JSON
    if start_idx != -1:
        json_str = text[start_idx:]
        # 补全缺少的闭合符号
        brace_count = json_str.count('{') - json_str.count('}')
        bracket_count = json_str.count('[') - json_str.count(']')
        repairs = []
        repairs.extend(['}'] * brace_count)
        repairs.extend([']'] * bracket_count)
        # 补全可能被截断的字符串
        in_string = json_str.count('"') % 2 != 0
        if in_string:
            repairs.insert(0, '"')
        repaired = json_str + ''.join(repairs)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
    # 策略 5：尝试提取 JSON 键值对作为兜底
    return _extract_key_values_from_text(text)

def _extract_key_values_from_text(text: str) -> dict:
    """
    从非标文本中提取关键信息（兜底策略）
    当 JSON 完全解析失败时，尝试用正则提取有明显标记的信息。
    返回部分可用的字段，而不是全空。
    """
    result = {
        "overview": {
            "years_of_experience": "解析失败",
            "education": "解析失败",
            "core_tech_stack": [],
            "current_role": "解析失败",
        },
        "strengths": [],
        "weaknesses": [],
        "job_matches": [],
        "summary": f"AI 返回格式异常，原始内容: {text[:200]}...",
        "_parse_error": True,  # 标记为解析失败，前端可特殊处理
    }
    # 尝试从文本中提取关键词
    years_match = re.search(r'(\d+[-~]\d+)?\s*年.*?经验', text)
    if years_match:
        result["overview"]["years_of_experience"] = years_match.group(0)
    return result


class ResumeService:
    """简历分析服务

    职责：
      - 接收简历文件 → 解析为纯文本
      - 构造 Prompt → 调用 LLM
      - 解析 LLM 返回的结构化 JSON

    不依赖向量库，只依赖 document_loader + llm_service
    """

    MAX_RESUME_LENGTH = 8000  # 简历文本最大字符数（超出截断）

    def __init__(self, llm_service: LLMService | None = None):
        self._llm = llm_service or get_llm_service()

    async def analyse(self, file_name: str, file_path: str) -> dict:
        """分析简历文件

        Args:
            file_name: 原始文件名（用于日志和元信息）
            file_path: 简历文件在服务端的临时路径

        Returns:
            结构化分析报告 dict

        Raises:
            ValueError: 文件解析失败或内容为空
            RuntimeError: LLM 调用失败
        """
        # 1. 解析简历为纯文本
        try:
            resume_text = load(file_path)
        except Exception as e:
            raise ValueError(f"简历文件解析失败: {e}")

        if not resume_text or len(resume_text.strip()) < 20:
            raise ValueError("简历内容过短，请检查文件是否有效")

        # 2. 截断过长文本
        is_truncated = False
        if len(resume_text) > self.MAX_RESUME_LENGTH:
            resume_text = resume_text[:self.MAX_RESUME_LENGTH]
            is_truncated = True

        # 3. 构造 User Prompt
        user_prompt = self._build_user_prompt(resume_text, is_truncated)

        # 4. 调用 LLM（非流式）
        try:
            raw_response = await self._llm.chat(
                system_prompt=RESUME_ANALYSIS_SYSTEM_PROMPT,
                user_message=user_prompt,
                temperature=0.3,
                max_tokens=3000,
            )
        except Exception as e:
            raise RuntimeError(f"AI 服务调用失败: {e}")

        # 5. 解析 JSON
        result = _safe_parse_json(raw_response)

        # 6. 附加元信息
        result["_meta"] = {
            "filename": file_name,
            "resume_length": len(resume_text),
            "is_truncated": is_truncated,
            "token_estimate": self._llm.count_tokens(resume_text),
            "resume_text": resume_text,
        }
        return result

    async def analyze_from_bytes(self, file_bytes: bytes, filename: str) -> dict:
        """从字节流分析简历（API 层直接调用）

        流程：写临时文件 → analyse → 清理临时文件
        """
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(filename).suffix.lower()
        temp_filename = f"resume_{uuid.uuid4().hex}{ext}"
        temp_path = upload_dir / temp_filename

        try:
            with open(temp_path, "wb") as f:
                f.write(file_bytes)
            return await self.analyse(filename, str(temp_path))
        finally:
            if temp_path.exists():
                temp_path.unlink()

    async def chat(
        self,
        resume_text: str,
        analysis_result: dict,
        message: str,
        history: list[dict] | None = None,
    ) -> str:
        """基于简历上下文的多轮追问

        Args:
            resume_text: 简历原始文本
            analysis_result: analyse() 返回的分析报告
            message: 用户当前的追问
            history: 本轮对话历史 [{"role":"user","content":"..."}, ...]

        Returns:
            LLM 回复文本
        """
        system_prompt = self._build_chat_system_prompt(
            resume_text, analysis_result, message, history
        )
        return await self._llm.chat(
            system_prompt=system_prompt,
            user_message=message,
        )

    async def chat_stream(
        self,
        resume_text: str,
        analysis_result: dict,
        message: str,
        history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """基于简历上下文的多轮追问（SSE 流式）

        Yields:
            data: {"type": "token", "data": "..."}
            data: {"type": "done"}
        """
        system_prompt = self._build_chat_system_prompt(
            resume_text, analysis_result, message, history
        )
        try:
            async for token in self._llm.chat_stream(system_prompt, message):
                if token:
                    yield sse_event("token", token)
        except Exception:
            logger.exception("简历追问流式调用失败")
            yield sse_event("token", "AI 服务暂时不可用，请稍后重试。")

        yield sse_event("done")

    def _build_chat_system_prompt(
        self,
        resume_text: str,
        analysis_result: dict,
        message: str,
        history: list[dict] | None = None,
    ) -> str:
        """构造追问的 System Prompt（流式与非流式共用）"""
        # 将分析报告压缩为摘要（避免 token 爆炸）
        analysis_summary = self._summarize_analysis(analysis_result)

        # 拼接历史
        history_text = "无"
        if history:
            parts = []
            for h in history[-6:]:  # 只保留最近 6 条
                role = "求职者" if h.get("role") == "user" else "专家"
                parts.append(f"**{role}**: {h.get('content', '')}")
            history_text = "\n".join(parts)

        return RESUME_CHAT_SYSTEM_PROMPT.format(
            resume_text=resume_text,
            analysis_summary=analysis_summary,
            history=history_text,
            message=message,
        )

    def _summarize_analysis(self, result: dict) -> str:
        """将分析报告压缩为简短摘要文本"""
        overview = result.get("overview", {})
        strengths = result.get("strengths", [])
        weaknesses = result.get("weaknesses", [])
        job_matches = result.get("job_matches", [])
        summary = result.get("summary", "")

        parts = [
            f"经验: {overview.get('years_of_experience', '-')}",
            f"学历: {overview.get('education', '-')}",
            f"技术栈: {', '.join(overview.get('core_tech_stack', []))}",
            f"当前职位: {overview.get('current_role', '-')}",
            f"综合评价: {summary}",
        ]

        if strengths:
            parts.append("优势: " + "; ".join(
                s.get("point", "") for s in strengths[:3]
            ))
        if weaknesses:
            parts.append("不足: " + "; ".join(
                w.get("point", "") for w in weaknesses[:3]
            ))
        if job_matches:
            parts.append("推荐岗位: " + ", ".join(
                f"{j.get('role', '')}({j.get('score', '-')}分)" for j in job_matches[:3]
            ))

        return "\n".join(parts)

    def _build_user_prompt(self, resume_text: str, is_truncated: bool) -> str:
        """
        构造发送给 LLM 的 User Prompt
        包含：
          - 简历内容
          - 截断提示（如果需要）
        """
        prompt_parts = [f"## 简历内容\n\n{resume_text}"]
        if is_truncated:
            prompt_parts.append(
                "\n\n⚠️ 注意：该简历内容超过长度限制，已被截断至前 "
                f"{self.MAX_RESUME_LENGTH} 字符。请基于已有信息进行分析，"
                "并在 summary 中注明'简历内容不完整，分析基于部分信息'。"
            )
        prompt_parts.append(
            "\n\n请严格按照要求的 JSON 格式输出分析报告，不要输出任何其他内容。"
        )
        return "\n\n".join(prompt_parts)

# ========== 全局单例 ==========
_resume_service_instance: ResumeService | None = None
def get_resume_service() -> ResumeService:
    """获取 ResumeService 单例"""
    global _resume_service_instance
    if _resume_service_instance is None:
        _resume_service_instance = ResumeService()
    return _resume_service_instance

def reset_resume_service() -> None:
    """重置单例（测试用）"""
    global _resume_service_instance
    _resume_service_instance = None