"""模拟面试「追问 / 翻页」决策评测（阶段 4 Step 5）：真调 LLM，量模型二选一做得对不对。

与另外两台仪器的分工（别混）：
  run_eval.py          —— 检索仪器：零 LLM，测「该找到的块找到没」+ 拒答规则。
  run_agent_eval.py    —— 多步 agent 仪器：测「该不该调工具 / 循环怎么收尾」。
  run_interview_eval.py—— 面试仪器：每条 case 只做【一次】chat_with_tools，
                          测「就当前题目，追问还是翻页」。

口径（写死在这里，要改就改这里）：
  - 每条 case 的 KB 片段【冻结在 interview_cases.json】里 → 不做检索、不依赖语料快照。
  - 上限是代码常量：followups_used >= cap 或 total_asked >= 12 → 强制 advance。
    这部分【确定、免费】，照 3.6 的 refuse 口径处理：不调模型、不检索，直接核对护栏。
  - 模型决策只对未触顶的 case 计分（decision_accuracy）。
  - 阶段转移 / 终止用【期望动作】驱动 _apply_decision 核对——测的是确定性的状态机，
    不是模型；模型选错会体现在 decision_accuracy，不污染转移指标。

用法（cwd 不必是 backend/，脚本会自举）：
    PYTHONIOENCODING=utf-8 python -m eval.run_interview_eval
    PYTHONIOENCODING=utf-8 python -m eval.run_interview_eval --repeat 3
"""
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

# 路径自举：对齐 run_agent_eval.py
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

from app.services.interview_agent_service import (                    # noqa: E402
    DECISION_TOOLS,
    INTERVIEW_FOLLOWUP_CAPS,
    INTERVIEW_MAX_QUESTIONS,
    InterviewAgentService,
    build_decision_messages,
)
from app.services.llm_service import get_llm_service                  # noqa: E402

EVAL_TEMPERATURE = 0.0
CASES_FILE = Path(__file__).parent / "interview_cases.json"
OUT_FILE = Path(__file__).parent / "interview_baseline_v2.json"
PROMPT_VERSION = "DECISION_SYSTEM_PROMPT v2（A 缺口 / B 提到未展开 / 否则 advance）"


class PinnedLLM:
    """薄壳：强制 temperature=0，不改服务"""

    def __init__(self, inner):
        self._inner = inner

    async def chat_with_tools(self, messages, tools, **kwargs):
        kwargs["temperature"] = EVAL_TEMPERATURE
        return await self._inner.chat_with_tools(messages, tools, **kwargs)


class BombLLM:
    async def chat_with_tools(self, *args, **kwargs):
        raise AssertionError("触顶 case 不应调用 LLM")


class BombRAG:
    async def retrieve(self, *args, **kwargs):
        raise AssertionError("触顶 case 不应检索 KB")


def load_cases() -> dict:
    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = data["cases"]

    ids = [c["id"] for c in cases]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        raise ValueError(f"case id 重复: {dup}")

    for c in cases:
        phase = c["phase"]
        if phase not in INTERVIEW_FOLLOWUP_CAPS:
            raise ValueError(f"{c['id']}: 未知阶段 {phase}")
        if c["cap"] != INTERVIEW_FOLLOWUP_CAPS[phase]:
            raise ValueError(
                f"{c['id']}: case 的 cap={c['cap']} 与服务常量 {INTERVIEW_FOLLOWUP_CAPS[phase]} 不一致"
            )
        if c["expect_action"] not in ("followup", "advance"):
            raise ValueError(f"{c['id']}: expect_action 非法")
        forced_by_code = (
            c["followups_used"] >= c["cap"]
            or c.get("total_asked", 0) >= INTERVIEW_MAX_QUESTIONS
        )
        if bool(c["expect_cap_forced"]) != forced_by_code:
            raise ValueError(
                f"{c['id']}: expect_cap_forced={c['expect_cap_forced']}，"
                f"但按常量应为 {forced_by_code}（followups={c['followups_used']}, cap={c['cap']}, "
                f"total={c.get('total_asked')}）"
            )
        if c["expect_cap_forced"] and c["expect_action"] != "advance":
            raise ValueError(f"{c['id']}: 触顶 case 的期望动作必须是 advance")
        if c.get("total_asked", 0) >= INTERVIEW_MAX_QUESTIONS and not c["expect_finished"]:
            raise ValueError(f"{c['id']}: 达到总题数上限必须 expect_finished=true")
    return data


def make_session(case: dict, resume_excerpt: str) -> dict:
    return {
        "session_id": "eval",
        "phase": case["phase"],
        "topic_index": case.get("topic_index", 0),
        "followups_used": case["followups_used"],
        "total_asked": case.get("total_asked", 0),
        "current_question": case["question"],
        "resume_excerpt": case.get("resume_excerpt") or resume_excerpt,
        "analysis": case.get("topics") or {},
    }


def _tool_calls(msg) -> list[dict]:
    out = []
    for call in getattr(msg, "tool_calls", None) or []:
        fn = getattr(call, "function", None)
        out.append({
            "name": getattr(fn, "name", ""),
            "arguments": getattr(fn, "arguments", ""),
        })
    return out


def check_spine(svc: InterviewAgentService, case: dict, resume_excerpt: str) -> dict:
    """确定性骨架：用【期望动作】推进一次，核对阶段转移 / 终止。不调模型。"""
    if case["expect_phase_after"] is None:
        return {}

    session = make_session(case, resume_excerpt)
    followup = "(期望追问)" if case["expect_action"] == "followup" else None
    svc._apply_decision(session, case["expect_action"], followup)

    phase_ok = session["phase"] == case["expect_phase_after"]
    finished = session["phase"] == "done" and not session.get("current_question")
    out = {
        "phase_after_expected": case["expect_phase_after"],
        "phase_after_actual": session["phase"],
        "phase_after_ok": phase_ok,
    }
    if case["expect_finished"]:
        out["finished_actual"] = finished
        out["termination_ok"] = finished
    return out


async def run_case(
    case: dict,
    resume_excerpt: str,
    model_svc: InterviewAgentService,
    forced_svc: InterviewAgentService,
) -> dict:
    row = {
        "id": case["id"],
        "phase": case["phase"],
        "kind": "forced" if case["expect_cap_forced"] else "model",
        "expected_action": case["expect_action"],
        "followups_used": case["followups_used"],
        "cap": case["cap"],
        "total_asked": case.get("total_asked"),
        "rationale": case.get("rationale", ""),
        "actual_action": None,
        "correct": False,
    }

    if case["expect_cap_forced"]:
        # 护栏是确定性的：BombLLM / BombRAG 一旦被调用就直接失败
        session = make_session(case, resume_excerpt)
        try:
            action, followup, forced = await forced_svc._decide(session, case["candidate_answer"])
            row["actual_action"] = action
            row["forced_flag"] = forced
            row["followup_question"] = followup
            row["correct"] = action == "advance" and forced is True
        except Exception as e:  # noqa: BLE001 - 评测要把异常记进报告，不中断整轮
            row["error"] = repr(e)
    else:
        messages = build_decision_messages(
            phase=case["phase"],
            question=case["question"],
            answer=case["candidate_answer"],
            followups_used=case["followups_used"],
            cap=case["cap"],
            resume_excerpt=case.get("resume_excerpt") or resume_excerpt,
            kb_hits=case.get("kb_snippets") or [],
        )
        try:
            msg = await model_svc._llm.chat_with_tools(messages, DECISION_TOOLS)
            action, followup = model_svc._parse_decision(msg)
            row["actual_action"] = action
            row["followup_question"] = followup
            row["raw_tool_calls"] = _tool_calls(msg)
            row["correct"] = action == case["expect_action"]
        except Exception as e:  # noqa: BLE001
            row["error"] = repr(e)

    row.update(check_spine(model_svc, case, resume_excerpt))

    verdict = "OK" if row["correct"] else "MISS"
    action = row.get("actual_action") or "ERROR"
    print(f"  [{row['id']:<34}] {row['phase']:<12} {row['kind']:<6} "
          f"expect={case['expect_action']:<8} got={action:<8} {verdict}")
    return row


def summarize(rows: list[dict]) -> dict:
    def _rate(group, pred):
        return round(sum(1 for r in group if pred(r)) / len(group), 4) if group else 0.0

    model_rows = [r for r in rows if r["kind"] == "model"]
    forced_rows = [r for r in rows if r["kind"] == "forced"]
    phase_rows = [r for r in rows if "phase_after_ok" in r]
    term_rows = [r for r in rows if "termination_ok" in r]
    errors = [r["id"] for r in rows if r.get("error")]

    by_phase = {}
    for phase in ("intro", "fundamentals", "project"):
        g = [r for r in model_rows if r["phase"] == phase]
        if g:
            by_phase[phase] = {
                "n": len(g),
                "correct": sum(1 for r in g if r["correct"]),
                "accuracy": _rate(g, lambda r: r["correct"]),
            }

    return {
        "n": len(rows),
        "decision": {
            "n": len(model_rows),
            "correct": sum(1 for r in model_rows if r["correct"]),
            "accuracy": _rate(model_rows, lambda r: r["correct"]),
            "by_phase": by_phase,
            "wrong_ids": [r["id"] for r in model_rows if not r["correct"]],
            "confusion": dict(Counter(
                f"{r['expected_action']}->{r['actual_action'] or 'ERROR'}" for r in model_rows
            )),
        },
        "cap_compliance": {
            "n": len(forced_rows),
            "correct": sum(1 for r in forced_rows if r["correct"]),
            "rate": _rate(forced_rows, lambda r: r["correct"]),
            "wrong_ids": [r["id"] for r in forced_rows if not r["correct"]],
        },
        "phase_transition": {
            "n": len(phase_rows),
            "correct": sum(1 for r in phase_rows if r["phase_after_ok"]),
            "rate": _rate(phase_rows, lambda r: r["phase_after_ok"]),
            "wrong_ids": [r["id"] for r in phase_rows if not r["phase_after_ok"]],
        },
        "termination": {
            "n": len(term_rows),
            "correct": sum(1 for r in term_rows if r["termination_ok"]),
            "rate": _rate(term_rows, lambda r: r["termination_ok"]),
            "wrong_ids": [r["id"] for r in term_rows if not r["termination_ok"]],
        },
        "errors": errors,
    }


def compute_stability(runs: list[list[dict]]) -> dict:
    n = len(runs[0])
    flaky = []
    for i in range(n):
        actions = {runs[k][i]["actual_action"] for k in range(len(runs))}
        if len(actions) > 1:
            flaky.append(runs[0][i]["id"])
    return {
        "runs": len(runs),
        "stable_actions": n - len(flaky),
        "flaky_action_ids": flaky,
    }


def render(summary: dict) -> str:
    d = summary["decision"]
    c = summary["cap_compliance"]
    p = summary["phase_transition"]
    t = summary["termination"]
    out = [
        f"  决策准确率: {d['correct']}/{d['n']} = {d['accuracy'] * 100:.1f}%"
        f"{'   错: ' + ', '.join(d['wrong_ids']) if d['wrong_ids'] else ''}",
        f"  上限遵从率（确定、不调模型）: {c['correct']}/{c['n']} = {c['rate'] * 100:.1f}%",
        f"  阶段转移正确率: {p['correct']}/{p['n']} = {p['rate'] * 100:.1f}%",
        f"  正常终止率: {t['correct']}/{t['n']} = {t['rate'] * 100:.1f}%",
        f"  错误: {summary['errors'] if summary['errors'] else '无'}",
        "  按阶段的决策准确率:",
    ]
    for phase, e in d["by_phase"].items():
        out.append(f"    {phase:<14}{e['correct']}/{e['n']}   {e['accuracy'] * 100:>5.1f}%")
    out.append(f"  混淆: {d['confusion']}")
    return "\n".join(out)


async def main() -> None:
    repeat = 1
    if "--repeat" in sys.argv:
        repeat = max(1, int(sys.argv[sys.argv.index("--repeat") + 1]))

    data = load_cases()
    cases = data["cases"]
    meta = data["meta"]
    resume_excerpt = meta["resume_excerpt"]

    model = get_llm_service().model
    model_svc = InterviewAgentService(
        cache=None,
        llm=PinnedLLM(get_llm_service()),
        rag=BombRAG(),
    )
    forced_svc = InterviewAgentService(cache=None, llm=BombLLM(), rag=BombRAG())

    n_model = sum(1 for c in cases if not c["expect_cap_forced"])
    print(f"=== 面试决策评测：{len(cases)} 条 case（模型 {n_model} / 触顶 {len(cases) - n_model}），"
          f"model={model}，temperature={EVAL_TEMPERATURE} ===")
    print(f"    语料无关：KB 片段冻结在 case 内，repeat={repeat}")

    runs: list[list[dict]] = []
    for r in range(repeat):
        print(f"\n----- run {r + 1}/{repeat} -----")
        rows = []
        for case in cases:
            rows.append(await run_case(case, resume_excerpt, model_svc, forced_svc))
        runs.append(rows)
        print(render(summarize(rows)))

    stability = None
    if repeat > 1:
        stability = compute_stability(runs)
        print("\n----- 稳定性（跨 run 动作一致性）-----")
        print(f"  动作一致: {stability['stable_actions']}/{len(cases)}"
              f"{'   飘: ' + ', '.join(stability['flaky_action_ids']) if stability['flaky_action_ids'] else ''}")

    payload = {
        "meta": {
            "date": "2026-10-21",
            "model": model,
            "temperature": EVAL_TEMPERATURE,
            "case_count": len(cases),
            "model_cases": n_model,
            "forced_cases": len(cases) - n_model,
            "cases_version": meta["version"],
            "decision_prompt": PROMPT_VERSION,
            "repeat": repeat,
            "expectation": "未触顶 case 由模型在 ask_followup / advance 中二选一；"
                           "触顶 case 由代码强制 advance（不调模型、不检索）",
            "note": "面试仪器：每条 case 只做一次 chat_with_tools；KB 片段冻结，不依赖语料快照",
        },
        "by_run": [summarize(rows) for rows in runs],
        "per_case": runs[-1],
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
