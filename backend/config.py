"""Application configuration using Pydantic settings."""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    secret_key: str = "change-me-in-production"
    debug: bool = False
    allowed_origins: str = "http://localhost:3000,http://localhost:8000"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v: str) -> str:
        return v  # kept as string; parsed to list via property below

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://voiceserve:voiceserve@localhost:5432/voiceserve"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl_menu: int = 3600
    redis_ttl_session: int = 1800
    redis_ttl_recommendations: int = 900

    # ── Saaras v3 STT ─────────────────────────────────────────────────────────
    saaras_api_key: str = ""
    saaras_api_url: str = "https://api.saaras.ai/v3"
    saaras_language: str = "en-IN"
    saaras_sample_rate: int = 16000
    saaras_noise_threshold: float = 0.02

    # ── Kimi K2 LLM ───────────────────────────────────────────────────────────
    kimi_api_key: str = ""
    kimi_api_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k2-instruct"
    kimi_max_tokens: int = 1024
    kimi_temperature: float = 0.3
    kimi_context_window: int = 32768

    # ── Bulbul v3 TTS ─────────────────────────────────────────────────────────
    bulbul_api_key: str = ""
    bulbul_api_url: str = "https://api.bulbul.ai/v3"
    bulbul_voice: str = "female_1"
    bulbul_language: str = "en-IN"
    bulbul_speed: float = 1.0
    bulbul_format: str = "pcm_16000"

    # ── Pinecone ──────────────────────────────────────────────────────────────
    pinecone_api_key: str = ""
    pinecone_environment: str = "us-east-1-aws"
    pinecone_index_name: str = "voiceserve-menu"
    pinecone_dimension: int = 1536
    pinecone_metric: str = "cosine"

    # ── Gemini ────────────────────────────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-pro"

    # ── FP-Growth ─────────────────────────────────────────────────────────────
    fpgrowth_min_support: float = 0.05
    fpgrowth_min_confidence: float = 0.3
    fpgrowth_max_recommendations: int = 5


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
