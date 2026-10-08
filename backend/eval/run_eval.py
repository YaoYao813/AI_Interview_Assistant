"""检索层评测：只测「该被找到的块有没有被找出来」+ 1.2 的拒答判定 + 1.4 的查询改写，零 LLM 调用。

两个指标族别混：§4.2/§4.3 是分数轴（能不能分开正负样本），§4.4 是内容轴（1.2 的免费规则）。

1.4 的接法：带 history 的题在 questions.json 里有冻结的 `rewrite` 字段（由生产
`_rewrite_query` 跑一次得来），检索用【改写后的问句】，而 1.2 的 grounding 仍用【原始问句】
——这句话本身是 1.4 的设计决定，不是实现细节。冻结值让评测保持零 LLM、确定性、免费。

用法（cwd 必须是 backend/，CHROMA_PERSIST_DIR 是相对路径）：
    PYTHONIOENCODING=utf-8 python -m eval.run_eval

设计说明见同目录 RUN_EVAL_HINTS.md。
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.infrastructure.embeddings import get_embedding
from app.repositories.base_vector_store import (
    DocumentChunk,
    is_grounded,
    missing_terms,
    query_identifiers,
)
from app.repositories.vector_store import get_vector_store

# 候选池取值必须与生产的 chroma_vector_store._POOL_MIN 一致。
# Chroma 的 HNSW 是近似检索、n_results 同时决定搜索强度：池子给 20 时
# 取到的前 5 名有 8/31 与收敛结果不同，给 5 更是 13/31（2026-09-28 实测）。
# 用 100（前 5 名不再随 n_results 变）后，从池里算出的 recall@k 才等于生产值。
TOP_K_POOL = 100
# 1.2 的拒答判定按生产口径算：生产交给 LLM 的是前 top_k=5 条，判定就看这 5 条。
PROD_TOP_K = 5
THRESHOLDS = [0.0, 0.3, 0.5]
STRATUM_ORDER = ["single_doc", "term", "multi_doc", "multi_turn", "multi_turn_cued", "refuse"]


def load_test_set() -> dict:
    test_file = Path(__file__).parent / "questions.json"
    return json.loads(test_file.read_text(encoding="utf-8"))


async def retrieve_all(questions: list[str]) -> list[list[DocumentChunk]]:
    """每条问题一轮检索，返回与 questions 等长的 hits 列表。

    分工（别把这两步合起来）：
      embedding 是网络调用 → 28 条合并成 1 次请求
      search 是本地 chroma 查询、且一次只收一个向量 → 必须逐条循环
    """
    embed = get_embedding()
    vectors = await embed.embed_documents(questions)      # 1 次网络请求

    store = get_vector_store()
    per_question: list[list[DocumentChunk]] = []
    for vec in vectors:
        # threshold=-1 表示真不过滤（源码是「similarity < threshold 就丢」）
        result = store.search(query_embedding=vec, top_k=TOP_K_POOL, threshold=-1)
        per_question.append(result.hits)
    return per_question


# ===== 以下四个是纯函数：不碰网络，可以单独喂假数据测 =====
def _hit_and_rank(
    fnames: list[str],
    expected: list[str],
    match_mode: str,
    refuse: bool,
) -> tuple[bool | None, int | None]:
    """从一串【按 rank 排好序】的文件名里算命中与首命中 rank（1-based）。

    这是整个评测里唯一算对错的逻辑，judge 和 sweep_threshold 都复用它——
    保证「无过滤」和「按阈值过滤」两套结果用的是同一把尺子。

    拒答题返回 (None, None)：它的判据是「返回 0 条」，不是命中。
    """
    if refuse:
        return None, None
    if not expected:
        return False, None

    want = set(expected)

    if match_mode == "all":
        # expected 全部出现完的那个位置（最慢的一个）
        remaining = set(want)
        for rank, f in enumerate(fnames, start=1):
            remaining.discard(f)
            if not remaining:
                return True, rank
        return False, None

    # any：第一个属于 expected 的位置
    for rank, f in enumerate(fnames, start=1):
        if f in want:
            return True, rank
    return False, None


def judge(case: dict, hits: list[DocumentChunk]) -> dict:
    """算单条题的结果（无过滤档位）。

    命中判定用【去重后】的集合，算 rank 用【未去重的原始顺序】——两者用的
    是同一个 fnames 列表，只是 rank 遍历时不需要去重。
    """
    expect = case["expect"]
    expected = expect.get("filenames", [])
    match_mode = expect.get("match", "any") # any / other
    refuse = bool(case.get("refuse")) # true / false

    top = [
        {
            "rank": i,
            "filename": h.metadata.get("filename", ""),
            "similarity": h.similarity,
            "chunk_id": h.chunk_id,
        }
        for i, h in enumerate(hits, start=1)
    ]
    fnames = [t["filename"] for t in top]

    hit, first_hit_rank = _hit_and_rank(fnames, expected, match_mode, refuse)

    # §4.1 的「文档数」列：top-5 里有几个不同文档 → 量化「同一文档占满引用位」
    distinct_top5 = len({t["filename"] for t in top[:5]})

    kept_by_threshold = {
        str(t): sum(1 for x in top if (x["similarity"] or 0) >= t)
        for t in THRESHOLDS
    }

    # 1.2 拒答判定：按生产口径只看前 PROD_TOP_K 条，用的是生产同一个函数
    prod_hits = hits[:PROD_TOP_K]
    missing = missing_terms(case["question"], prod_hits)

    return {
        "id": case["id"],
        "stratum": case["stratum"],
        "question": case["question"],
        "retrieval_query": case.get("rewrite") or case["question"],
        "expected": expected,
        "match": match_mode,
        "refuse": refuse,
        "hit": hit,
        "first_hit_rank": first_hit_rank,
        "distinct_docs_top5": distinct_top5,
        "returned_unfiltered": len(top),
        "kept_by_threshold": kept_by_threshold,
        "grounded": is_grounded(case["question"], prod_hits),
        "missing_terms": missing,
        "why": case.get("why", ""),
        "top": top,
    }


def grounding_verdict(judged: list[dict]) -> dict:
    """1.2 免费规则的拒答成绩单。

    两件事分开算，不能合成一个数：
      拒答准确率 = 负样本里被判「知识库答不了」的比例（越高越好）
      误杀率     = 正样本里被判拒答的比例（越低越好，**这个才是风险**）
    弃权（问题里没有英文标识符）不计入拒对，也不计入误杀。
    """
    refuses = [j for j in judged if j["refuse"]]
    positives = [j for j in judged if not j["refuse"]]

    rejected = [j for j in refuses if not j["grounded"]]
    killed = [j for j in positives if not j["grounded"]]
    abstained = [j for j in judged if not query_identifiers(j["question"])]

    return {
        "refuse_total": len(refuses),
        "refuse_rejected": len(rejected),
        "refuse_accuracy": round(len(rejected) / len(refuses), 4) if refuses else 0.0,
        "refuse_leaked": [j["id"] for j in refuses if j["grounded"]],
        "positive_total": len(positives),
        "positive_killed": len(killed),
        "kill_rate": round(len(killed) / len(positives), 4) if positives else 0.0,
        "killed_ids": [j["id"] for j in killed],
        "abstained_ids": [j["id"] for j in abstained],
        "note": "弃权 = 问题里没有 >=3 字符的英文标识符，规则不表态，交回老逻辑",
    }


def aggregate(judged: list[dict]) -> dict:
    """按 stratum 聚合 recall@k 与 MRR。

    MRR 的分母是【该 stratum 的题目总数】，不是命中数——没命中的题按 0 计入，
    否则 MRR 就失去了「检索不到要受罚」的含义。
    拒答题不参与 MRR/recall，它的指标在 sweep_threshold 里算。
    """
    by_stratum: dict[str, dict] = {}

    for stratum in STRATUM_ORDER:
        group = [j for j in judged if j["stratum"] == stratum]
        if not group:
            continue

        entry: dict = {"n": len(group)}

        if stratum == "refuse":
            entry["note"] = "拒答题看 by_threshold 的拒答准确率"
            by_stratum[stratum] = entry
            continue

        for k in (1, 3, 5, 10):
            hit_k = sum(
                1 for j in group
                if j["first_hit_rank"] is not None and j["first_hit_rank"] <= k
            )
            entry[f"recall@{k}"] = round(hit_k / len(group), 4)

        mrr = sum(
            (1.0 / j["first_hit_rank"]) for j in group if j["first_hit_rank"] is not None
        ) / len(group)
        entry["mrr"] = round(mrr, 4)

        by_stratum[stratum] = entry

    return by_stratum


def sweep_threshold(judged: list[dict], t: float) -> dict:
    """在已有 hits 上离线过滤出该阈值档位的结果。

    过滤条件是 similarity >= t（要和源码的 `< threshold` 就丢对齐，写成 > 会差一条边界）。
    这里不需要重新检索——因为生产代码的阈值本来就是后置过滤，
    在完整 20 条上过滤 == 拿 threshold=t 去调 search()。
    """
    rows: list[dict] = []
    for j in judged:
        kept = [x for x in j["top"] if (x["similarity"] or 0) >= t]
        fnames = [x["filename"] for x in kept]
        hit, rank = _hit_and_rank(fnames, j["expected"], j["match"], j["refuse"])
        rows.append({**j, "hit": hit, "first_hit_rank": rank, "kept": len(kept)})

    refuse_rows = [r for r in rows if r["refuse"]]
    refuse_accuracy = (
        sum(1 for r in refuse_rows if r["kept"] == 0) / len(refuse_rows)
        if refuse_rows else 0.0
    )

    return {
        "threshold": t,
        "by_stratum": aggregate(rows),
        "refuse_accuracy": round(refuse_accuracy, 4),
        "refuse_correct": sum(1 for r in refuse_rows if r["kept"] == 0),
        "refuse_total": len(refuse_rows),
        "avg_returned": round(sum(r["kept"] for r in rows) / len(rows), 2),
    }


def _fmt_stratum_row(stratum: str, entry: dict) -> str:
    if "recall@1" not in entry:
        return f"  {stratum:<12}{entry['n']:>3}    —（拒答题另算）"
    return (
        f"  {stratum:<12}{entry['n']:>3}"
        f"{entry['recall@1']:>10.3f}{entry['recall@3']:>10.3f}"
        f"{entry['recall@5']:>10.3f}{entry['recall@10']:>10.3f}"
        f"{entry['mrr']:>9.4f}"
    )


def render(judged: list[dict], by_stratum: dict, by_threshold: dict, grounding: dict) -> str:
    out: list[str] = []
    w = out.append

    # ---- §4.1 逐条明细（必须有，聚合数字看不出差异在哪）----
    w("=" * 100)
    w("§4.1 逐条明细")
    w("=" * 100)
    for j in judged:
        w("")
        w(f"[{j['id']}] {j['stratum']}  {j['question']}")
        if j.get("retrieval_query") and j["retrieval_query"] != j["question"]:
            w(f"      ↳ 1.4 改写后检索: {j['retrieval_query']}")
        if j["refuse"]:
            w(f"      期望: <应当拒答>")
        else:
            w(f"      期望: {', '.join(j['expected'])}  (match={j['match']})")

        shown = j["top"][:5]
        actual = ", ".join(
            f"{x['filename']}@{x['similarity']:.4f}" for x in shown
        )
        w(f"      实际 top-5: {actual or '（无）'}")

        if j["refuse"]:
            w(f"      命中: -   首命中rank: -   返回 {j['returned_unfiltered']} 条"
              f"   不同文档(top5) {j['distinct_docs_top5']}")
        else:
            mark = "OK" if j["hit"] else "MISS"
            rank = j["first_hit_rank"] if j["first_hit_rank"] is not None else "-"
            w(f"      命中: {mark}   首命中rank: {rank}   返回 {j['returned_unfiltered']} 条"
              f"   不同文档(top5) {j['distinct_docs_top5']}")

        verdict = "拒答" if not j["grounded"] else "放行"
        w(f"      1.2判定: {verdict}   缺失英文术语: {', '.join(j['missing_terms']) or '—'}")

    # ---- §4.2 按 stratum 聚合（无过滤档位）----
    w("")
    w("=" * 100)
    w("§4.2 按 stratum 聚合（threshold 无过滤）")
    w("=" * 100)
    w(f"  {'stratum':<12}{'n':>3}{'recall@1':>10}{'recall@3':>10}"
      f"{'recall@5':>10}{'recall@10':>10}{'MRR':>9}")
    for stratum, entry in by_stratum.items():
        w(_fmt_stratum_row(stratum, entry))

    # ---- §4.3 threshold 分档矩阵 ----
    w("")
    w("=" * 100)
    w("§4.3 threshold 分档矩阵")
    w("=" * 100)
    # 表头的中文列宽要比行值窄：Python 按【字符数】补齐，但中文在控制台占 2 列，
    # 5 个汉字补到 14 字符会显示成 19 列，整行就歪了。下面的宽度是按显示宽度反推的。
    w(f"  {'threshold':<10}{'拒答准确率':>9}{'平均返回条数':>8}"
      f"{'single_doc@5':>14}{'term@5':>10}{'multi_turn@5':>14}")
    for t_str, data in by_threshold.items():
        bs = data["by_stratum"]

        def _r5(name: str) -> str:
            e = bs.get(name, {})
            return f"{e['recall@5']:.3f}" if "recall@5" in e else "—"

        refuse = f"{data['refuse_correct']}/{data['refuse_total']} = {data['refuse_accuracy'] * 100:.1f}%"
        w(f"  {t_str:<10}{refuse:>14}{data['avg_returned']:>14.2f}"
          f"{_r5('single_doc'):>14}{_r5('term'):>10}{_r5('multi_turn'):>14}")

    # ---- §4.4 1.2 拒答判定（免费规则）----
    g = grounding
    w("")
    w("=" * 100)
    w("§4.4 1.2 拒答判定（免费规则 / 生产口径 top-5）")
    w("=" * 100)
    w(f"  拒答准确率（负样本被判「知识库答不了」）: "
      f"{g['refuse_rejected']}/{g['refuse_total']} = {g['refuse_accuracy'] * 100:.1f}%")
    w(f"  误杀率（正样本被判拒答）            : "
      f"{g['positive_killed']}/{g['positive_total']} = {g['kill_rate'] * 100:.1f}%"
      f"{'   误杀: ' + ', '.join(g['killed_ids']) if g['killed_ids'] else ''}")
    w(f"  漏答（规则表态了但没拦住）          : {', '.join(g['refuse_leaked']) or '—'}")
    w(f"  弃权（问题里没有 >=3 字符英文标识符）: {len(g['abstained_ids'])} 条 "
      f"→ {', '.join(g['abstained_ids']) or '—'}")

    return "\n".join(out)


async def main() -> None:
    test_set = load_test_set()
    cases = test_set["questions"]

    # §7.2 语料快照护栏：语料一变，历史数字全失效，必须当场停下
    store = get_vector_store()
    actual = store.get_chunk_count()
    snapshot = test_set["meta"]["corpus_snapshot"]["chunk_count"]
    if actual != snapshot:
        print(f"[FATAL] 语料已变：chroma={actual}，评测集写的是 {snapshot}")
        print("        历史数字全部失效，先更新 questions.json 的 corpus_snapshot")
        sys.exit(1)

    print(f"=== 检索层评测：{len(cases)} 条题，候选池 top_k={TOP_K_POOL} ===")
    print(f"    语料快照核对通过：{actual} chunk")
    n_rewritten = sum(1 for c in cases if c.get("rewrite"))
    print(f"    1.4 冻结改写：{n_rewritten} 条用改写后问句检索（其余用原问题）")

    # 1.4：带冻结 rewrite 的题用改写后的问句检索；1.2 的 grounding 仍在 judge() 里用原问题
    hits_per_question = await retrieve_all([c.get("rewrite") or c["question"] for c in cases])
    judged = [judge(c, h) for c, h in zip(cases, hits_per_question)]

    by_stratum = aggregate(judged)
    by_threshold = {str(t): sweep_threshold(judged, t) for t in THRESHOLDS}
    grounding = grounding_verdict(judged)

    print(render(judged, by_stratum, by_threshold, grounding))

    payload = {
        "meta": {
            "date": "2026-10-08",
            "top_k_pool": TOP_K_POOL,
            "prod_top_k": PROD_TOP_K,
            "thresholds": THRESHOLDS,
            "chunk_count": actual,
            "question_count": len(cases),
            "questions_version": test_set["meta"]["version"],
            "grounding_rule": "RETRIEVAL_TERM_GROUNDING: 问题里 >=3 字符的英文标识符必须出现在前 top_k 块里",
            "rewrite_rule": "RETRIEVAL_QUERY_REWRITE: 带 history 的题用 questions.json 里冻结的 rewrite 检索；grounding 仍用原始 question",
            "rewritten_cases": [c["id"] for c in cases if c.get("rewrite")],
        },
        "per_question": judged,          # 形状见 RUN_EVAL_HINTS.md §6
        "by_stratum": by_stratum,
        "by_threshold": by_threshold,
        "by_grounding": grounding,
    }
    out = Path(__file__).parent / "baseline_v5.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")


if __name__ == "__main__":
    # Windows 控制台是 GBK，报表里的中文/符号会让 print 抛 UnicodeEncodeError
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # search() 每次会 logger.info 打一行完整距离数组，28 条约等于刷屏
    logging.getLogger("app.repositories.chroma_vector_store").setLevel(logging.WARNING)
    asyncio.run(main())
