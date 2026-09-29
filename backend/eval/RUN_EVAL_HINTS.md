# run_eval.py 提示文档

这是给你自己写 `run_eval.py` 用的**规格**，不是代码。里面写的是「要调什么、怎么算、哪里容易错」。
照着实现顺序一节一节做，每节都有验收标准。

**这份文档原本设计成脚手架**（脚本写完就删），但用户 2026-09-28 明确要求**留着，别删**——
理由：它记着「算法定义 / 容易算错的地方 / 已知陷阱」，脚本每加一项优化都要回来改它。

---

## 0. 目标与产物

| | |
|---|---|
| 输入 | `backend/eval/questions.json`（31 条 / 6 stratum，已全部 verified） |
| 产物 | `backend/eval/baseline_v3.json` —— 机器可读，改完 diff 它 |
| 历史留档 | `baseline_v1.json`（候选池 20，仪器不合格、数字不可复现）；`baseline_v2.json`（候选池 100，只含检索指标） |
| stdout | 文本报表（给人看） |
| 成本 | **零 LLM 调用**。31 次检索，秒级，免费 |
| 时机 | **改检索/拒答代码之前**必须先跑出 baseline，否则没有对照 |

只测**检索层 + 拒答判定**，不测回答质量。判据是文件名，不是 chunk_id（chunk_id 在阶段 2.1 重建索引后全部失效）。

**文件名版本 = 仪器版本**，不是任务编号：v1 = 池 20、v2 = 池 100、v3 = 池 100 + 拒答判定。
加一项测量就 +1，旧文件不覆盖（每项优化都要能回退）。

---

## 1. 输入契约

`questions.json` 里每条题的结构（`_schema` 字段里有完整说明）：

```python
{
  "id": "B01",
  "stratum": "term",                    # single_doc / term / multi_doc / multi_turn / refuse
  "question": "...",
  "history": [],                        # 只有 multi_turn 非空；本脚本用不到，见 §7.3
  "expect": {
    "match": "any",                     # any=命中任一即可 / all=必须全部命中
    "filenames": ["concurrent-hash-map-source-code.md"],
    "substrings": ["sizeCtl"]           # 可选，块级复核；本脚本可以先不用
  },
  "refuse": false,
  "verified": true,
  "why": "..."
}
```

**`filenames` 比对用的是 metadata 里的 `filename`**，值是**纯文件名**（`path.name`，见 `document_loader.py:126`），不含路径。

---

## 2. 要调的 API（签名别猜）

```python
from app.infrastructure.embeddings import get_embedding
from app.repositories.vector_store import get_vector_store
```

**Embedding**（`app/infrastructure/embeddings.py`）：

```python
emb = get_embedding()
vecs = await emb.embed_documents([q1, q2, ..., q28])   # -> list[list[float]]，1024 维
# 或单条：vec = await emb.embed_query(q)               # -> list[float]
```

`embed_documents` 收 **list** → **28 条题一次请求搞定**，别写成 28 次循环（28 次网络往返纯属浪费）。
风险：一次失败=全军覆没。所以要么整批失败就整批重试，要么就接受「一次不成重跑整个脚本」。28 条远低于厂商上限（参考 `ingest_corpus.py` 里 `BATCH_WARN_CHUNKS = 128` 的警戒线）。

**检索**（`app/repositories/chroma_vector_store.py:63`）：

```python
store = get_vector_store()          # 不传参数，读 config 里的 collection
result = store.search(
    query_embedding=vec,
    top_k=20,                       # §5 已定 20
    threshold=0,                    # 见 §7.1
)
# result: SearchResult(hits=[DocumentChunk, ...], total=len(hits), query="")
# chunk.chunk_id / chunk.content / chunk.metadata / chunk.similarity
# chunk.metadata: {"document_id","filename","chunk_index","chunk_size","created_at"[,"file_size"]}
```

**三个必须知道的点**

1. `search()` 是**同步**方法，`embed_documents` 是 **async**。
   → 结构上就写成 `async def main()` + `asyncio.run(main())`，里面 `await` 完 embedding 再调 `search()`。
2. `search()` 内部是 `collection.query(n_results=top_k)` **之后**再按阈值过滤（第 87 行 `similarity < threshold` 就丢掉，见 §7.1）。**这是 1.1 的 bug 所在**，也是本脚本「一次检索榨出所有指标」这个设计成立的依据。
3. **不要 import `RAGService`**。`RAGService.__init__` 会调 `get_llm_service()`，让 `LLM_API_KEY` 变成脚本的前置条件——而这个脚本根本不调 LLM。直接用 `get_embedding()` + `get_vector_store()`，这正是 `rag_service.py:108-113` 干的那两步，结果完全等价。

---

## 3. 算法定义（逐个精确，这是最容易算错的地方）

设检索返回的完整列表为 `hits`（已按相似度降序），`fnames = [h.metadata["filename"] for h in hits]`。

### 3.1 命中判定 `hit`

```python
if match == "any":
    hit = any(f in fnames_within_topk for f in expected)
else:  # match == "all"
    hit = all(f in fnames_within_topk for f in expected)
```

- `fnames_within_topk` 是**去重后**的文件名集合（同一文件多个 chunk 命中只算一次）
- **去重只用于判定命中；算 rank 时必须用未去重的原始顺序**（否则 rank 会算错）

### 3.2 首命中 rank `first_hit_rank`

**1-based**（第一个位置是 1，不是 0）。没有命中则记 `None`。

```python
# match == "any"：第一个 ∈ expected 的位置
first_hit_rank = next((i for i, f in enumerate(fnames, start=1) if f in expected), None)

# match == "all"：expected 全部出现完的那个位置（即最慢的那个）
# 例：expected = {A, B}，rank 1 是 A，rank 4 是 B → first_hit_rank = 4
```

### 3.3 MRR

```
MRR = (Σ 1/first_hit_rank) / N        # 没命中的题贡献 0
```

**分母 N 是「参与 MRR 的题目总数」，不是「命中的题目数」**——这是最常见的算错点。把没命中的当 0 加进去，MRR 才会反映「检索不到」的惩罚。

**拒答题（`refuse: true`）不参与 MRR**，它们的指标是 §3.5 的拒答准确率。别混进去，否则 MRR 会被污染。

### 3.4 recall@k

按 stratum 分别算，`k ∈ {1, 3, 5, 10}`：

```
recall@k(stratum) = 该 stratum 内 first_hit_rank <= k 的题数 / 该 stratum 总题数
```

**⚠️ 2026-09-28 实测更正：候选池必须取 100，且「截断列表」并不等价于「减少 `n_results`」。**
Chroma 的 HNSW 是近似检索，`n_results` 同时决定搜索强度：池子给小了，返回的前几名本身就不准。
拿 5 / 20 / 100 三个池子比生产 `top_k=5` 的返回，与「收敛结果」不同的题目数分别是
13/31、8/31、0/31；C03 那道甚至出现「真·top1（sim 0.5897）在 n_results=5/10/20 里完全不出现、
要 50 才出现」。所以池子小时从池里算出的 `recall@5` **不代表**生产值。
池子取 100 后 `search(top_k=100)[:5]` 与生产走同一条代码路径，数字才对得上。

### 3.5 拒答准确率（**必须分档位算**）

```
拒答准确率(t) = 该档位下返回 0 条的拒答题数 / 拒答题总数
```

其中「返回 0 条」= 对 `hits` 用阈值 t 过滤之后 `len == 0`。

**为什么必须分档位**：`threshold=0` 时 E01–E08 是**必然有命中**的（这正是 1.2 的缺陷本身）。
三个档位 `t ∈ {0, 0.3, 0.5}` 出来的三个数，就是「0.3 到底有没有区分力」的全部证据——
**一列数字，不是你的判断**。0.3 那一档就是现行生产配置。

**⚠️ 2026-09-28 实测：这条路已经被证明死掉。** 0.3 档位在 31×100 个 chunk 上一个都没过滤掉，
拒答准确率 **0/8**；0.5 档位才 2/8。而且正样本最低分 0.5885 < 负样本最高分 0.7214 —— 
**不存在能分开正负样本的阈值**（见下面 3.5b）。

### 3.5b 规则拒答准确率（1.2 起，与 3.5 是**两把不同的尺子**）

```
拒答准确率(规则) = 负样本中被判「知识库答不了」的条数 / 拒答题总数
误杀率(规则)     = 正样本中被判拒答的条数 / 正样本总数     ← 这个才是风险
```

判据来自 `base_vector_store.is_grounded(question, hits[:prod_top_k])`，**生产同一个函数**：

```
问题里长度 >= 3 的英文标识符，必须全部出现在交给 LLM 的那 top_k 个块里
一个英文标识符都没有 → 弃权（返回 True，交回老逻辑）
```

**别把 3.5 和 3.5b 合成一个数**：3.5 是「分数能不能分」，3.5b 是「内容能不能分」。
实测 3.5b = 拒对 6/8、误杀 0/23；弃权 9 条（A07/C01/C02/C03/C05/C06/C07/E03/E07）。
漏的 E03（雪花算法）/ E07（领域驱动设计）是纯中文专有名词 —— 没有分词器抓不到。

**`prod_top_k` 必须写 5**：生产交给 LLM 的是 `top_k=5` 条，拿 100 条池子去判会虚高。

### 3.6 threshold 离线模拟

```python
kept = [h for h in hits if h.similarity >= t]     # 注意是 >=
```

**方向要和 `search()` 里对齐**：源码是 `similarity < threshold` 就丢（`chroma_vector_store.py:87`），
所以**保留条件是 `>=`**。写成 `>` 的话边界值会差一条。

用 `kept` 重算 §3.1–§3.5 的全部指标，就得到该档位的一行。

---

## 4. 报表格式

### 4.1 逐条明细（**必须有，不能只给聚合数字**）

理由见 `questions.json` 的标注纪律：n=28 且命中是二值的 → 差 2 条以内不可区分，聚合数字看不出来差异在哪。

```
id   stratum     期望文件              实际 top-5（文件名@相似度）                        首命中rank  命中  返回  文档数
B01  term        concurrent-hash-...   concurrent-hash-map@0.7212, aqs@0.6133, ...        1         ✅    20    7
C01  multi_turn  concurrent-hash-...   memory-area@0.5597, jvm-intro@0.5402, ...          None      ❌    20    12
E01  refuse      <拒答>                kubernetes相关@0.4102, ...                          -        ❌    20    9
```

列的含义：

| 列 | 说明 |
|---|---|
| `首命中rank` | §3.2，1-based；拒答题和未命中都打 `None` |
| `命中` | §3.1；**拒答题这一列无意义**，打 `-`，它的判据是「返回 0 条」 |
| `返回` | **`threshold=0` 时的返回条数（恒等于 top_k=20）**，以及三个档位过滤后各剩几条 |
| `文档数` | top-5 里有几个**不同文档** → 量化「发现 2：同一文档占满引用位」（阶段 1.5 的输入） |

`返回` 这一列是诊断 1.1 的关键：**没有它，「阈值调高 → recall 下降」会被误读成优化失败**，实际上那是后置过滤的必然结果。

### 4.2 按 stratum 聚合

```
stratum      题目数  recall@1  recall@3  recall@5  recall@10  MRR     备注
single_doc      8      ?/8       ?/8       ?/8        ?/8     0.???   ← 1.1 的判据
term            5      ...                                        ← 2.5 混合检索的判据
multi_doc       3      ...      （match=all，只看 @5）
multi_turn      4      ...                                        ← 基线应接近 0，1.4 的起点
refuse          8      —                                            ← 看下方拒答准确率
```

### 4.3 threshold 分档矩阵

```
threshold   single_doc  term  multi_doc  multi_turn   refuse拒答准确率   平均返回条数
0.0(无过滤)   ...                                            0/8 = 0%         100.0
0.3(现行)     ...                                            0/8 = 0%         100.0
0.5           ...                                            2/8 = 25%         67.9
```

### 4.4 拒答判定（1.2 免费规则）

```
拒答准确率（负样本被判「知识库答不了」）: 6/8 = 75.0%
误杀率（正样本被判拒答）              : 0/23 = 0.0%
漏答（规则表态了但没拦住）            : E03, E07
弃权（问题里没有 >=3 字符英文标识符）  : 9 条 → A07, C01, ...
```

四个数必须分开列。只报「拒答准确率 75%」而不报误杀率是**误导**——
误杀是这条规则唯一的真实风险（把能答的问题拒掉，比漏答更难被用户接受）。

---

## 5. 已定的参数

| 参数 | 值 | 理由 |
|---|---|---|
| 候选池 `top_k` | **100** | 2026-09-28 实测 20 太小：HNSW 的搜索强度随 `n_results` 缩，20 档位下前 5 名有 8/31 与收敛结果不同（5 档位 13/31）。100 档位前 5 名稳定，且与生产的 `_POOL_MIN` 一致 |
| threshold 档位 | `[0, 0.3, 0.5]` | 0 = 假阴性全暴露；0.3 = 现行生产；0.5 = 看抬高后是否先砍正样本（阶段 0 发现 1 的验证） |
| 判据 | `filename` | 不标 chunk_id |
| 命中比较 | 去重后集合 | 但 rank 用原始顺序 |
| `prod_top_k` | **5** | 生产交给 LLM 的条数；拒答判定必须按这个口径算，不能用 100 的池子 |
| 英文标识符长度下限 | **3** | 排掉 RC/RR/IO 这类缩写。长度 2 时 D03 会被误杀（实测） |

---

## 6. 落盘 JSON schema

定好这个 schema，后面 1.1/2.5 改完可以机器 diff。

```json
{
  "meta": {
    "date": "2026-09-28",
    "top_k_pool": 100,
    "prod_top_k": 5,
    "thresholds": [0, 0.3, 0.5],
    "chunk_count": 2393,
    "question_count": 31,
    "questions_version": 4,
    "grounding_rule": "RETRIEVAL_TERM_GROUNDING: 问题里 >=3 字符的英文标识符必须出现在前 top_k 块里"
  },
  "per_question": [
    {
      "id": "B01",
      "stratum": "term",
      "question": "...",
      "expected": ["concurrent-hash-map-source-code.md"],
      "match": "any",
      "refuse": false,
      "top": [
        {"rank": 1, "filename": "concurrent-hash-map-source-code.md", "similarity": 0.7212, "chunk_id": "..."}
      ],
      "first_hit_rank": 1,
      "hit": true,
      "distinct_docs_top5": 3,
      "kept_by_threshold": {"0": 20, "0.3": 12, "0.5": 4},
      "grounded": true,
      "missing_terms": []
    }
  ],
  "by_stratum": {
    "term": {"n": 5, "recall@1": 0.8, "recall@3": 1.0, "recall@5": 1.0, "recall@10": 1.0, "mrr": 0.85}
  },
  "by_threshold": {
    "0.3": {"by_stratum": { "...": "同上结构" }, "refuse_accuracy": 0.125, "avg_returned": 8.4}
  },
  "by_grounding": {
    "refuse_total": 8, "refuse_rejected": 6, "refuse_accuracy": 0.75,
    "refuse_leaked": ["E03", "E07"],
    "positive_total": 23, "positive_killed": 0, "kill_rate": 0.0, "killed_ids": [],
    "abstained_ids": ["A07", "C01", "..."],
    "note": "弃权 = 问题里没有 >=3 字符的英文标识符，规则不表态，交回老逻辑"
  }
}
```

`per_question` 里 `top` 建议存 **完整 20 条**（不是只存 top-5），这样将来算 `recall@10`、看长尾都不用重跑。

---

## 7. 五个必须处理的坑

### 7.1 `threshold=0` 到底是不是「不过滤」

源码条件是 `chunk.similarity < threshold` 就丢。`threshold=0` 意味着**相似度为负的会被丢掉**。
bge-m3 是归一化向量、cosine 距离，实际相似度都 > 0，所以 `0` 在实践中没问题——
但严格「不过滤」应该传 `-1`。

**建议传 `-1`**，并在报告里注明「候选池取的是无过滤的 20 条」。省得将来某条 query 真出了负值，你会怀疑是自己算错了。

### 7.2 语料快照护栏（很值钱的一条）

脚本开头先做：

```python
actual = store.get_chunk_count()                                  # chroma 里的真实块数
expected = questions_json["meta"]["corpus_snapshot"]["chunk_count"]  # 2393
if actual != expected:
    print(f"语料已变：chroma={actual} 评测集写的是 {expected}")
    print("历史数字全部失效，需要先更新 questions.json 的 corpus_snapshot")
    sys.exit(1)
```

**没有这道护栏，将来重建索引后你会拿旧 baseline 比新结果，然后得出完全错误的结论**，而且毫无痕迹。

### 7.3 multi_turn 的基线必须只喂 `question`

看 `rag_service.py`：

- 第 170 行：`embed_query(question)` —— **history 没进 embedding**
- 第 212 行：`_build_context(hits, history)` —— history 只拼进**给 LLM 看的 prompt**

所以 C01–C04 的「那 1.7 里是怎么做的？」这种**零实体问题**，现在去 embedding 必然检索不到。
**这不是 bug，这是 1.4 要修的起点。** 报告里单独标注这 4 条为「1.4 起点」，别让它污染结论。

给将来留一个 `--rewrite` 开关的位置，但**这一版不实现**（1.4 还没做，没有东西可开关）。

### 7.4 Windows 环境的三个坑

1. **控制台是 GBK**：报表里有 ✅ / ❌ / ⚠️ 的话 `print` 会抛 `UnicodeEncodeError`。
   → 跑的时候带 `PYTHONIOENCODING=utf-8`，或者脚本开头就：

   ```python
   for s in (sys.stdout, sys.stderr):
       try: s.reconfigure(encoding="utf-8", errors="replace")
       except Exception: pass
   ```

   （`ingest_corpus.py:144-149` 就是这么干的，抄它。或者干脆全用 `[OK]/[MISS]` 这种 ASCII 标记。）

2. **`eval/` 目录没有 `__init__.py`**（`scripts/` 有）。所以 `python -m eval.run_eval` 现在会失败。
   两个选择：给 `eval/` 加一个空的 `__init__.py`（和 `scripts/` 保持一致），
   或者 `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` 然后 `python eval/run_eval.py`。
   **推荐前者**，跟既有跑法统一。

3. **cwd 必须是 `backend/`**：`CHROMA_PERSIST_DIR = "./data/chroma"` 是相对路径。
   跑法：`cd backend && PYTHONIOENCODING=utf-8 python -m eval.run_eval`

4. **后端服务在跑的话可能抢 chroma 的 sqlite 锁**。只读查询一般没事，但报
   `database is locked` 就先停掉 uvicorn。

### 7.5 报错不要静默跳过

某条题的 embedding 失败（限流/网络）→ 记进该条的 `error` 字段并在报表里显式打出来，
**不要 `continue` 掉**。静默跳过会让分母变小，而分母变小会让 recall **看起来变好**。

---

## 8. 建议的实现顺序（每步都有验收标准）

| 步 | 做什么 | 验收标准 |
|---|---|---|
| 1 | 只做「读 1 条题（A01）→ embed → search(top_k=20) → 打印 20 个 `文件名@相似度`」 | 能看到 `arraylist-source-code.md` 出现在前列 |
| 2 | 加 §3.1 命中判定 + §3.2 rank，跑全 28 条，**只打 §4.1 逐条明细** | A01/A02/B01/B04/B05 应为 ✅（这几条是「唯一文档 + 专名」，没有理由不命中） |
| 3 | 加 §4.2 按 stratum 聚合 | `multi_turn` 的 recall@5 应该接近 0（C01–C04） |
| 4 | 加 §3.6 threshold 离线模拟 + §4.3 分档矩阵 | `threshold=0` 那行的拒答准确率应当是 **0%** |
| 5 | 加 §6 落盘 + §7.2 护栏 | 生成 `backend/eval/baseline_v1.json` |

**第 3 步和第 4 步是「读结果」，不是「改代码」**——如果某条题的失败你解释不清是判据问题还是检索问题，先别往下走，那说明题有问题。

### 自查清单（写完对着过一遍）

- [ ] 零 LLM 调用：grep 一下脚本里没有 `llm` / `chat` / `RAGService`
- [ ] 没动 `app/` 下任何文件（这一步只是测量）
- [ ] MRR 的分母是「参与 MRR 的题目总数」，不是命中数
- [ ] 拒答题没有混进 MRR
- [ ] rank 是 1-based
- [ ] threshold 过滤用 `>=`（和源码的 `< threshold` 对齐）
- [ ] 命中判定用去重集合，rank 用原始顺序
- [ ] 有语料快照护栏
- [ ] embedding 失败有显式报错，没静默跳过
- [ ] 28 条全部有结果（没有的必须显式标 error）

---

## 9. 明确不要做的（架构约束）

- ❌ **不要建策略基类 / 注册装饰器 / 插件框架**。整个脚本只需要**一个** `retrieve(question) -> hits` 函数作为边界。将来 1.1/2.5 改检索时只改这一个函数。
- ❌ 不要调 LLM、不要算「回答质量」。那要 LLM 裁判，噪声大且随模型漂移，留到最后做少量人工抽查。
- ❌ 不要把 threshold 写进 `config.py` 当新配置项——**那是 1.1 的任务**，这个脚本只测量、不改代码。
- ❌ 不要为了「跑得更快」引入并发/线程池。28 条题串行也就几秒，复杂度不值。
