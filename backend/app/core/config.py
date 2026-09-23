from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "ForgeAI"
    version: str = "0.1.0"

    # Database — no default: application fails fast at startup if unset
    database_url: str

    # Repository storage & cloning
    repository_storage_path: str = "./data/repositories"
    git_clone_timeout: int = 120
    max_file_size_bytes: int = 2 * 1024 * 1024

    # Local code indexing & embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384
    embedding_device: str = "auto"


    # Chunking configuration (in lines)
    chunk_size: int = 50
    chunk_overlap: int = 10

    # RAG & Retrieval configuration
    rag_top_k: int = 5
    rag_max_context_chars: int = 4000

    # Agent configuration
    agent_max_iterations: int = 8
    agent_max_tool_calls: int = 12
    agent_max_context_chars: int = 12000
    agent_max_file_read_lines: int = 500

    # LLM & Agent Provider
    llm_provider: str = "mock"  # "mock", "ollama", or "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")



settings = Settings()

