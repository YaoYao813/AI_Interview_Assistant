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

    # File upload
    UPLOAD_DIR: str = "./data/documents"
    ALLOWED_EXTENSIONS: list[str] = [".pdf", ".docx", ".doc", ".md", ".txt"]
    MAX_UPLOAD_SIZE_MB: int = 20

    # Text splitter
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # LLM (DashScope)
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen3-max"
    LLM_MAX_TOKENS: int = 2048
    LLM_TEMPERATURE: float = 0.7
    LLM_REQUEST_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 3

    # Embedding (DashScope)
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_DIMENSION: int = 1024

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
