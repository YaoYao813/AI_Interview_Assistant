"""Agent 轨迹评测（阶段 3.6）：真调 LLM，量「模型选不选工具 / 循环能不能正常收尾」。

与 run_eval.py 的分工（别混成一台仪器）：
  run_eval.py       —— 检索仪器：零 LLM、确定性、免费；测「该找到的块找到没」+ 拒答规则。
  run_agent_eval.py —— agent 仪器：真调 LLM、有随机性、花钱；测「模型在循环里怎么决策」。
两台仪器共享同一套 questions.json（31 题）、同一个语料快照护栏，但 baseline 各自独立。

期望（写死在这条口径里，要改就改这里）：
  - 31 题都是技术题（K8s / ClickHouse / 雪花算法 也是「该查 KB 的技术问题」）
    → 期望模型【都调】search_knowledge_base。工具选择正确率的分母就是这 31。
  - 8 道 refuse 题额外期望：检索工具命中「知识库答不了」分支。这一步是【确定性、免费】的
    ——靠的是 is_grounded 这个纯函数，不需要 LLM 当裁判。

指标：工具选择正确率 / 按 stratum 分解 / 步数分布 / 正常终止率 / refuse 命中率 /
      **模型改写**（模型实际传给 search 工具的 query 是否 ≠ 原问句）。

为什么要抓 query：agent 通路的 retrieve() 收不到 history，_rewrite_query 空转，
送进向量库的句子完全等于模型自己组的 query。所以「模型在真调库时到底改写没」
只能靠抓工具入参来回答——这决定要不要给工具补传 history（方向 B）。

用法（cwd 必须是 backend/，CHROMA_PERSIST_DIR 是相对路径）：
    PYTHONIOENCODING=utf-8 python -m eval.run_agent_eval
    PYTHONIOENCODING=utf-8 python -m eval.run_agent_eval --repeat 3    # 稳定性探针

温度固定 0：工具选择是决策任务，temp=0 最可复现。但 DeepSeek 在 temp=0 下也只是
【近似】确定（服务端批处理 / MoE），不是位级复现——所以 baseline 先单跑，再用
--repeat 3 探一次稳定性，确认「三遍差几题」再决定要不要改成多数表决。
"""
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

# 路径自举：无论从哪调用都能跑（对齐 agent_trace_demo.py）——
# `from app...` 能导入，且 .env 与 ./data/chroma 这些【相对 cwd】的路径也对得上。
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

from app.repositories.vector_store import get_vector_store          # noqa: E402
from app.services.agent_service import AgentService                 # noqa: E402
from app.services.interview_service import InterviewService         # noqa: E402
from app.services.llm_service import get_llm_service                # noqa: E402
from app.services.rag_service import get_rag_service                # noqa: E402
from eval.run_eval import STRATUM_ORDER, load_test_set              # noqa: E402

EVAL_TEMPERATURE = 0.0
REFUSE_MARKER = "知识库中没有"   # search_knowledge_base 的拒答分支开头，必须与 agent_service 一致
OUT_FILE = Path(__file__).parent / "agent_baseline_v3.json"


class PinnedLLM:
    """薄壳：强制 temperature=0。不改 AgentService.run()，只在「调 LLM」这条接缝上覆盖。"""

    def __init__(self, inner):
        self._inner = inner

    async def chat_with_tools(self, messages, tools, **kwargs):
        kwargs["temperature"] = EVAL_TEMPERATURE
        return await self._inner.chat_with_tools(messages, tools, **kwargs)


class CapturingRAG:
    """薄壳：抓模型实际传给 search_knowledge_base 的 query —— 这就是【模型做的改写】。

    不改 AgentService，只在「工具调下游 retrieve」这条接缝上观测：agent 通路里
    retrieve() 收不到 history（_rewrite_query 因此空转），所以送进向量库的那句话
    完全等于模型自己组的 query。抓它，才能回答「模型到底改写没」。
    """

    def __init__(self, inner):
        self._inner = inner
        self.queries: list[str] = []

    async def retrieve(self, query, top_k=5, **kwargs):
        self.queries.append(query)
        return await self._inner.retrieve(query, top_k=top_k, **kwargs)

    def drain(self) -> list[str]:
        qs, self.queries = self.queries, []
        return qs


async def run_once(agent: AgentService, cases: list[dict], capture: "CapturingRAG") -> list[dict]:
    """把 31 题逐条喂给真实 agent，记录每条的工具选择 / 步数 / 收尾状态 / 模型给的 query。

    顺序执行——RUN_EVAL_HINTS §9 禁并发；且 LLM 有速率限制，并发只会更难复现。
    """
    rows: list[dict] = []
    for c in cases:
        # 多轮题必须带 history：C 组是「那 1.7 里是怎么做的？」这类指代句，
        # 不带上下文模型没法判断该检索什么——不带 history 测的是残缺输入，不是 agent 能力。
        r = await agent.run(c["question"], history=c.get("history"))
        queries = capture.drain()   # 模型实际送进向量库的句子（= 模型做的改写）
        tools = [s["tool"] for s in r["steps"]]
        search_steps = [s for s in r["steps"] if s["tool"] == "search_knowledge_base"]
        row = {
            "id": c["id"],
            "stratum": c["stratum"],
            "refuse": bool(c.get("refuse")),
            "question": c["question"],
            "has_history": bool(c.get("history")),
            "called_tools": tools,
            "called_search": "search_knowledge_base" in tools,
            "search_refused": any(REFUSE_MARKER in s["result"] for s in search_steps),
            "search_queries": queries,
            "query_rewritten": bool(queries) and any(q.strip() != c["question"].strip() for q in queries),
            "steps": len(r["steps"]),
            "stopped": r["stopped"],
            "answer": (r["answer"] or "")[:200],
        }
        rows.append(row)
        tool_str = ",".join(tools) if tools else "—"
        q_str = "  q=" + " | ".join(q[:60] for q in queries) if queries else ""
        print(f"  [{row['id']}] {row['stratum']:<14} search={'Y' if row['called_search'] else 'n'}"
              f" refuse_hit={'Y' if row['search_refused'] else 'n'}"
              f" steps={row['steps']} stopped={row['stopped']:<9} tools={tool_str}{q_str}")
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    positives = [r for r in rows if not r["refuse"]]
    refuses = [r for r in rows if r["refuse"]]
    stop = Counter(r["stopped"] for r in rows)
    steps_hist = Counter(r["steps"] for r in rows)

    by_stratum = {}
    for stratum in STRATUM_ORDER:
        g = [r for r in rows if r["stratum"] == stratum]
        if g:
            by_stratum[stratum] = {
                "n": len(g),
                "call_rate": round(sum(1 for r in g if r["called_search"]) / len(g), 4),
            }

    def _rate(group, pred):
        return round(sum(1 for r in group if pred(r)) / len(group), 4) if group else 0.0

    called_rows = [r for r in rows if r["called_search"]]
    rewritten = [r for r in called_rows if r["query_rewritten"]]

    return {
        "n": n,
        "tool_call_rate": _rate(rows, lambda r: r["called_search"]),
        "positives": {"n": len(positives), "call_rate": _rate(positives, lambda r: r["called_search"])},
        "refuse": {
            "n": len(refuses),
            "call_rate": _rate(refuses, lambda r: r["called_search"]),
            "hit_refuse_branch": sum(1 for r in refuses if r["search_refused"]),
            "hit_rate": _rate(refuses, lambda r: r["search_refused"]),
            "ids_hit": [r["id"] for r in refuses if r["search_refused"]],
            "ids_miss": [r["id"] for r in refuses if not r["search_refused"]],
        },
        "termination": {
            "done": stop.get("done", 0),
            "max_steps": stop.get("max_steps", 0),
            "error": stop.get("error", 0),
            "done_rate": round(stop.get("done", 0) / n, 4),
        },
        "steps_histogram": {str(k): steps_hist[k] for k in sorted(steps_hist)},
        "query_rewrite": {
            "called": len(called_rows),
            "rewritten": len(rewritten),
            "rewritten_ids": [r["id"] for r in rewritten],
        },
        "by_stratum": by_stratum,
    }


def compute_stability(runs: list[list[dict]]) -> dict:
    """跨 run 的一致性：同一条题，三遍的「调不调 search」「refuse 命中没」是否一模一样。

    这是判断 N=1 读数可不可信的依据——一致率高才敢单跑当基线。
    """
    n = len(runs[0])
    flaky_call, flaky_refuse = [], []
    for i in range(n):
        calls = {runs[k][i]["called_search"] for k in range(len(runs))}
        refs = {runs[k][i]["search_refused"] for k in range(len(runs))}
        if len(calls) > 1:
            flaky_call.append(runs[0][i]["id"])
        if len(refs) > 1:
            flaky_refuse.append(runs[0][i]["id"])
    return {
        "runs": len(runs),
        "stable_call": n - len(flaky_call),
        "flaky_call_ids": flaky_call,
        "stable_refuse": n - len(flaky_refuse),
        "flaky_refuse_ids": flaky_refuse,
    }


def render(summary: dict) -> str:
    out = [
        f"  工具选择正确率 (叫了 search 的比例): {summary['tool_call_rate'] * 100:.1f}%"
        f"  ({summary['positives']['n']} 正样本 {summary['positives']['call_rate'] * 100:.1f}%"
        f" / {summary['refuse']['n']} 拒答样本 {summary['refuse']['call_rate'] * 100:.1f}%)",
        f"  refuse 题命中「知识库答不了」分支: "
        f"{summary['refuse']['hit_refuse_branch']}/{summary['refuse']['n']} = {summary['refuse']['hit_rate'] * 100:.1f}%"
        f"{'   未命中: ' + ', '.join(summary['refuse']['ids_miss']) if summary['refuse']['ids_miss'] else ''}",
        f"  正常终止率 (stopped=done): {summary['termination']['done']}/{summary['n']} = "
        f"{summary['termination']['done_rate'] * 100:.1f}%"
        f"  (max_steps={summary['termination']['max_steps']}, error={summary['termination']['error']})",
        f"  步数分布: {summary['steps_histogram']}",
        f"  模型改写（query != 原问句）: {summary['query_rewrite']['rewritten']}/{summary['query_rewrite']['called']} 次调用"
        f"{'   改写过的: ' + ', '.join(summary['query_rewrite']['rewritten_ids']) if summary['query_rewrite']['rewritten_ids'] else ''}",
        "  按 stratum 的工具调用率:",
    ]
    for stratum, e in summary["by_stratum"].items():
        out.append(f"    {stratum:<16}{e['n']:>3} 题   {e['call_rate'] * 100:>5.1f}%")
    return "\n".join(out)


async def main() -> None:
    repeat = 1
    if "--repeat" in sys.argv:
        repeat = max(1, int(sys.argv[sys.argv.index("--repeat") + 1]))

    test_set = load_test_set()
    cases = test_set["questions"]

    # 语料快照护栏：与 run_eval 同一道闸——语料一变，历史数字全失效，当场停。
    store = get_vector_store()
    actual = store.get_chunk_count()
    snapshot = test_set["meta"]["corpus_snapshot"]["chunk_count"]
    if actual != snapshot:
        print(f"[FATAL] 语料已变：chroma={actual}，评测集写的是 {snapshot}")
        sys.exit(1)

    model = get_llm_service().model
    print(f"=== Agent 轨迹评测：{len(cases)} 条题，model={model}，temperature={EVAL_TEMPERATURE} ===")
    print(f"    语料快照核对通过：{actual} chunk；repeat={repeat}")

    capture = CapturingRAG(get_rag_service())
    agent = AgentService(
        llm=PinnedLLM(get_llm_service()),
        rag=capture,
        interview=InterviewService(cache=None),
    )

    runs: list[list[dict]] = []
    for r in range(repeat):
        print(f"\n----- run {r + 1}/{repeat} -----")
        rows = await run_once(agent, cases, capture)
        runs.append(rows)
        print(render(summarize(rows)))

    stability = None
    if repeat > 1:
        stability = compute_stability(runs)
        print("\n----- 稳定性（跨 run 一致性）-----")
        print(f"  调用决策一致: {stability['stable_call']}/{len(cases)}"
              f"{'   飘: ' + ', '.join(stability['flaky_call_ids']) if stability['flaky_call_ids'] else ''}")
        print(f"  refuse 判定一致: {stability['stable_refuse']}/{len(cases)}"
              f"{'   飘: ' + ', '.join(stability['flaky_refuse_ids']) if stability['flaky_refuse_ids'] else ''}")

    payload = {
        "meta": {
            "date": "2026-10-14",
            "model": model,
            "temperature": EVAL_TEMPERATURE,
            "question_count": len(cases),
            "chunk_count": actual,
            "questions_version": test_set["meta"]["version"],
            "repeat": repeat,
            "system_prompt_variant": "技术事实必检索（即使历史聊过）；仅寒暄/身份/闲聊不检索",
            "expectation": "31 题全为技术题，期望都调 search_knowledge_base；8 道 refuse 题额外期望命中拒答分支",
            "note": "agent 仪器：真调 LLM、有随机性、花钱；与 run_eval.py 的检索仪器互不相干",
        },
        "by_run": [summarize(rows) for rows in runs],
        "per_question": runs[-1],       # 末次 run 的逐条明细
        "stability": stability,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {OUT_FILE}")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.getLogger("app.repositories.chroma_vector_store").setLevel(logging.WARNING)
    asyncio.run(main())
