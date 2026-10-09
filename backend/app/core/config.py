from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "AI Interview Assistant"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    CORS_ORIGINS: str = "http://localhost:5173"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    # Chroma
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_COLLECTION: str = "interview_docs"

    # 检索后置过滤（阶段 1.1）
    # 实际底线 = max(threshold 参数, RETRIEVAL_RELATIVE_RATIO * top1 相似度)，
    # 在候选池里过滤完再截断到 top_k（池子下限见 chroma_vector_store._POOL_MIN）。0 = 关闭相对规则。
    # 相对规则只用来砍长尾（同一文档占满引用位），不负责判断「要不要回答」：
    # baseline 实测正样本最低分 0.5885 < 负样本最高分 0.7214，分数轴上分不开。
    RETRIEVAL_RELATIVE_RATIO: float = 0.0

    # 拒答判定（阶段 1.2）
    # 问题里的英文标识符（长度 >= 3）必须出现在检索到的块里，否则判「知识库答不了」，
    # 直接返回固定话术、不调 LLM。免费规则、确定性、零额外调用。
    # 实测（31 条评测题）：8 条负样本拒对 6 条，23 条正样本误杀 0 条。
    # 漏掉的两条是纯中文专有名词（雪花算法 / 领域驱动设计）——没有分词器抓不到，
    # 留给 2.5 稀疏检索（BM25 天然覆盖术语）。False = 退回「只有 0 命中才拒答」。
    RETRIEVAL_TERM_GROUNDING: bool = True

    # 查询改写（阶段 1.4）
    # history 非空 且 问句含指代词（它/那/上面/前面）时，先让 LLM 把追问改写成可独立检索的
    # 完整问句，再拿去 embed —— 只改「取回什么」，不改「问模型什么」（prompt 里仍是原始 question）。
    # 拒答判定（1.2）也仍用原始 question：改写会往问句里补标识符，用它判会单调变严；
    # 且改写出错时不该连累拒答。False = 完全退回「直接检索原始问题」。
    # 实测（7 条多轮题）：multi_turn 4/4 MISS → 4/4 命中；multi_turn_cued 的 C03 排名 1→5
    # （仍在 top_k=5 内，生产口径不变）——该层本就是为 1.4 建的回归护栏，这是已知代价。
    RETRIEVAL_QUERY_REWRITE: bool = False

    # File upload
    UPLOAD_DIR: str = "./data/documents"
    ALLOWED_EXTENSIONS: list[str] = [".pdf", ".docx", ".doc", ".md", ".txt"]
    MAX_UPLOAD_SIZE_MB: int = 20

    # Text splitter
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    # 切分策略（阶段 2.1）：
    #   recursive       = 旧的递归字符切分，作为基线与回退
    #   markdown_header = 按 #/##/### 标题切；无标题文档（PDF/本地八股）递归兜底
    # 只在【入库时】生效——查询链路从不切分，所以改它必须重建语料才看得到效果。
    CHUNK_STRATEGY: str = "markdown_header"
    # 最小块下限：同一父标题下连续的、短于该值的兄弟 section 会被合并，避免标题
    # 密集的文档（JavaGuide 有 1205 个 H3）产出大量碎块。仅 markdown_header 生效。
    CHUNK_MIN_SIZE: int = 200

    # LLM
    # 默认值与 .env 保持一致：本文件此前写的是 DashScope/qwen3-max，
    # 与实际运行配置不符，读代码会得出完全错误的结论。
    # 模型只在厂商 /models 列出的 deepseek-flash / deepseek-v4-pro 里选
    # （deepseek-chat 是个未列出的兼容别名，实测会静默路由到 deepseek-flash）。
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-flash"
    LLM_MAX_TOKENS: int = 2048
    LLM_TEMPERATURE: float = 0.7
    LLM_REQUEST_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 3

    # Embedding
    # 实际跑的是硅基流动的 BAAI/bge-m3（1024 维），不是 DashScope。
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://api.siliconflow.cn/v1"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIMENSION: int = 1024

    # Rerank（阶段 2.2）
    # 检索之上的策略，不改索引、不改库。坐在 search() 与拒答判定之间，只改「顺序」
    # 和「喂给 LLM 的是哪几条」。RERANK_ENABLED 是唯一的 A/B 开关；下面两个是它的
    # 参数，不是独立策略。默认 False = 完全退回当前行为（v6）。
    RERANK_ENABLED: bool = False
    # 跨编码器每对 (query, doc) 都要跑一次模型，成本正比于候选数；且 doc 向量无法
    # 预算缓存，所以它只能当「粗排之后的精排」，不能当粗排本身。
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    # 拿去重排的候选数：从粗排结果里取前 N 条喂跨编码器。太小救不回被错排的，
    # 太大白花钱——比 top_k=5 大得多、又不至于让单次问答明显变慢的折中。
    RERANK_CANDIDATES: int = 30

    # 上下文 token 预算（阶段 2.4）
    # 只约束【喂给 LLM 的上下文】，不参与拒答判定——截断在拒答判定【之后】做，
    # 所以 recall / grounding 一个都不动，只新增一个 context_tokens 测量。
    # 整个上下文（历史 + 检索来源）不超过 CONTEXT_MAX_TOKENS；其中历史最多
    # HISTORY_MAX_TOKENS，剩下的留给来源。超预算时从排名最低的来源（hits 尾部）丢，
    # 至少留 1 条——保证最高分来源不被丢。
    # 刻意【不用】llm_service.max_context_tokens：那是模型窗口（硬上限 65536），
    # 不是成本/质量意义上的预算（软目标），语义不同，兜底值 16385 也不可信。
    CONTEXT_MAX_TOKENS: int = 6000
    HISTORY_MAX_TOKENS: int = 1500

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
