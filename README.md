# AI Interview Assistant

面向求职者的 AI 面试辅助平台：RAG 知识问答、简历分析、模拟面试、学习路线。

这个项目的重点不是「把大模型接进来」，而是**把检索质量和 Agent 决策变成可复现的数字**：
仓库内置三套独立评测仪器和版本化基线，每次修改都有对照；失败的实验结果也保留下来，而不是从简历里删掉。

`FastAPI` · `ChromaDB` · `Redis` · `DeepSeek` · `BAAI/bge-m3` · `Vue 3` · `Element Plus`

## 功能

- **RAG 知识问答**：文档上传 / 切分 / 向量化，SSE 流式回答，引用来源可追溯；知识库外的问题在检索层拒答，零额外 LLM 调用。
- **简历分析**：解析 PDF / DOCX，分析简历与 JD 的匹配度、优势与短板，支持多轮追问。
- **模拟面试**：
  - 线性模式：一次生成题目，逐题给出评分、点评与参考答案（流式输出）。
  - **动态追问 Agent**：答完一题后，模型在 `ask_followup` / `advance` 之间二选一；阶段流程、每阶段追问上限、整场总题数由确定性状态机约束。
- **学习路线**：按目标岗位生成分阶段学习计划。
- **知识库管理**：上传、分页检索、格式筛选、删除、统计。

## 架构

```
Vue 3 + Element Plus
        │  HTTP / SSE
        ▼
FastAPI  /api/v1
   ├─ rag / knowledge      → Chroma（2898 chunks） + OpenAI 兼容 LLM
   ├─ resume / roadmap     → 文档解析 + LLM
   ├─ interview            → 线性出题（确定性流程）
   └─ interview/agent      → 阶段状态机 + Function Calling 决策
        │
        ▼
Redis（会话 / 缓存，TTL 30 min）
```

后端按 `api / service / repository / infrastructure` 分层：

- `api/v1`：路由、参数校验、SSE 建流；
- `services`：业务编排（RAG、面试、Agent 循环），不直接碰存储；
- `repositories`：Redis 会话仓库、向量库封装；
- `infrastructure`：文档解析、切分、Chroma / BM25 / Rerank 实现。

两条面试路径互不影响：线性面试是已验证的旗舰路径，动态追问 Agent 是新增入口
（`/interview/agent/*`，独立的 Redis key 前缀），出问题时可以整条回退。

## 评测：这个项目的核心

三台仪器分工明确，互不混用。基线文件的命名规则是**文件名 = 仪器版本，从不覆盖旧文件**，
每次改检索或提示词都能回退对照。

| 仪器 | 入口 | 测什么 | 最近结果（2026-10） |
|---|---|---|---|
| 检索评测 | `eval/run_eval.py` | 31 题 / 6 层，**零 LLM**：该找到的块找到没 + 拒答规则 | recall@5 22/23（默认配置；开 rerank 后 23/23）；8 道拒答题正确拒答 6 道；23 道正样本 0 误杀 |
| Agent 轨迹评测 | `eval/run_agent_eval.py` | 31 题 × 3 runs，温度 0：该不该调工具、循环能否收尾 | 工具调用 31/31；正常收尾 31/31；拒答分支 6/8；跨 run 一致 31/31 |
| 面试决策评测 | `eval/run_interview_eval.py` | 16 case × 3 runs，温度 0：追问还是翻页 | 决策 8/11（72.7%）；上限遵从 5/5；阶段转移 9/9；正常终止 2/2；跨 run 一致 16/16 |

口径说明：

- 检索仪器的拒答题里，有 2 道是纯中文专有名词（雪花算法 / 领域驱动设计），没有英文标识符可抓，
  规则弃权——所以是 **6/8 而非 6/6**；正样本误杀 0/23。
- Agent / 面试仪器真调 LLM，有随机性；因此固定温度 0 并跑 3 次，除准确率外还报告**跨 run 动作一致性**。
- 面试评测把 KB 片段冻结在 case 内，不依赖语料快照；触顶 case 用 `BombLLM` 证明「不调模型也能强制翻页」。
- 检索评测本身零 LLM：多轮改写的模型输出被冻结进 `questions.json`，保持确定性、免费、可复现。

### 关键测量

- **阈值判拒答这条路被数据证死**：正样本最低分 0.5885 反而低于负样本最高分 0.7214，
  两个分布倒挂，不存在能分开正负样本的阈值（0.3 档实测一个块都没过滤掉）→ 改为
  「问题里的英文标识符必须命中检索结果」的确定性规则。
- **HNSW 是近似检索**：`n_results` 同时决定搜索强度。候选池取 5 / 20 / 100 时，
  分别有 13 / 8 / 0 题与收敛结果不同 → 改为「先取大池（100）→ 过滤 → 截断 top_k」。
- **Rerank 有明确收益**：recall@5 22/23 → 23/23、recall@1 17/23 → 18/23；
  但每次查询多一次跨编码器调用，因此保留为配置开关（默认关闭）。
- **混合检索是负结果**：BM25 + RRF 在这份语料上与稠密检索持平（22/23），
  multi_turn 反而从 1.0 掉到 0.75 → 默认关闭，结论留在 `baseline_v9.json`。

## 快速开始

环境：Python 3.11+、Node 18+、Docker（只需 Redis）。

```bash
# 1. 启动 Redis（仓库根目录）
docker compose up -d

# 2. 后端
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 填入 LLM 与 Embedding 的 API Key
python -m uvicorn app.main:app --reload
# 健康检查: http://localhost:8000/health

# 3. 前端
cd ../frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

### 准备知识库

仓库不包含语料（体积与授权原因）。二选一：

- **界面上传**：启动后在「知识库管理」页上传 markdown / PDF / DOCX，即可对话；
- **批量灌入**（以 JavaGuide 为例，Apache-2.0）：

```bash
cd backend
mkdir -p data/corpus/javaguide
# 将 JavaGuide 的 docs/ 内容放进 data/corpus/javaguide/
python -m scripts.ingest_corpus --dry-run     # 先看统计
python -m scripts.ingest_corpus --rebuild     # 清空并重建索引
```

注意：换 embedding 模型后必须 `--rebuild`，旧向量与新的向量空间不兼容。

## 复现评测

```bash
cd backend
python -m eval.run_eval                 # 检索层：零 LLM、免费
python -m eval.run_agent_eval           # Agent 轨迹：会调用 LLM
python -m eval.run_interview_eval       # 面试决策：会调用 LLM
```

Windows 终端如遇编码问题，加 `PYTHONIOENCODING=utf-8`。所有结果写入 `backend/eval/*.json`，
与历史基线同名不覆盖。

## 目录结构

```
backend/
  app/
    api/v1/           # 路由（rag / knowledge / resume / interview / interview_agent / agent）
    services/         # 业务编排与提示词
    repositories/     # Redis 会话、向量库
    infrastructure/   # 文档解析、切分、检索实现
  eval/               # 三套评测仪器 + 版本化基线
  scripts/            # 语料入库
  requirements.txt
frontend/
  src/views/          # 知识问答 / 简历分析 / 线性面试 / 动态追问 / 学习路线 / 知识库管理
  src/utils/sse.js    # 统一的 SSE 解析
```

## 已知边界

- 纯中文专有名词（雪花算法、领域驱动设计）没有英文标识符，拒答规则会漏判；
  同义说法与分词是下一步的抓手。
- `multi_doc` 的 recall@1 为 0：三个多文档题的目标块都在 top-5，但不在第一位，粗排仍需更强的精排。
- 面试决策准确率 8/11，且自动化只测「动作对不对」，**追问质量仍需人工抽查**。
- 单机 demo，无鉴权与多租户；语料、向量库、上传文件均不入 git。

## License

代码以学习与求职展示为目的。内置语料（如 JavaGuide）遵循其原始许可证（Apache-2.0），不随仓库分发。
