from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    app_name: str = "企业知识库 Agent 平台"
    app_version: str = "1.0.0"
    api_prefix: str = "/api"

    database_url: str = Field(default=f"sqlite:///{DATA_DIR / 'research_agent.db'}")
    upload_dir: Path = DATA_DIR / "uploads"
    chroma_db_dir: Path = DATA_DIR / "chroma_db"
    chroma_collection_name: str = "enterprise_knowledge"
    logs_dir: Path = LOGS_DIR
    query_log_path: Path = LOGS_DIR / "query_log.jsonl"

    chunk_size: int = 800
    chunk_overlap: int = 120
    default_top_k: int = 4
    memory_window_size: int = 8
    enable_llm_tool_planner: bool = False
    enable_llm_generation: bool = True

    embedding_provider: Literal["sentence_transformers", "openai"] = "sentence_transformers"
    embedding_fallback: Literal["error", "lexical"] = "error"
    embedding_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    openai_embedding_model: str = "text-embedding-3-small"

    llm_provider: Literal["ollama", "openai", "deepseek", "qwen"] = "ollama"
    llm_timeout: int = 60
    llm_max_retries: int = 0
    llm_retry_backoff_seconds: float = 0.5
    llm_temperature: float = 0.2

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_num_predict: int = 4096

    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    qwen_api_key: Optional[str] = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    fallback_when_llm_unavailable: bool = True

    # Operations API 认证密钥，用于保护 /operations/execute 等敏感端点
    operations_api_key: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_db_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
