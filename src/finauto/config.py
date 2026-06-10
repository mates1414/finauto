from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment / .env (prefix FINAUTO_)."""

    model_config = SettingsConfigDict(
        env_prefix="FINAUTO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: Literal["gemini", "claude"] = "gemini"
    gemini_model: str = "gemini-2.5-pro"
    claude_model: str = "claude-opus-4-8"
    locale: Literal["tr", "en"] = "tr"
    data_dir: Path = Path("data")


def get_settings() -> Settings:
    # Load .env into os.environ so the provider SDKs (google-genai reads
    # GEMINI_API_KEY, anthropic reads ANTHROPIC_API_KEY) can find their keys.
    load_dotenv()
    return Settings()
