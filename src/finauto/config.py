from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["gemini", "claude", "openai"]

# Pipeline stages that route to an LLM. Each may pin its own provider/model;
# unset values fall back to the global `llm_provider` + that provider's model.
Stage = Literal["extract", "discover", "report"]


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment / .env (prefix FINAUTO_)."""

    model_config = SettingsConfigDict(
        env_prefix="FINAUTO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Global default provider + per-provider model (current behaviour; unchanged).
    llm_provider: Provider = "gemini"
    gemini_model: str = "gemini-2.5-pro"
    claude_model: str = "claude-opus-4-8"

    # OpenAI-compatible provider (DeepSeek, OpenRouter, Together, local servers, …).
    # Text-only — the PDF is converted to text first (lower fidelity, much cheaper).
    # The SDK reads the key from OPENAI_API_KEY; point base_url at the vendor, e.g.
    # https://api.deepseek.com or https://openrouter.ai/api/v1. None = real OpenAI.
    openai_model: str = "deepseek-chat"
    openai_base_url: Optional[str] = None

    # Per-stage provider/model overrides (Phase 3, A6). A None provider falls
    # back to `llm_provider`; a None model falls back to that provider's default
    # model. Defaults follow the routing table in phase3.md: extraction on the
    # global default (Gemini), discovery on Gemini (Google Search grounding),
    # narrative report on Claude (Opus 4.8).
    extract_provider: Optional[Provider] = None
    extract_model: Optional[str] = None
    discover_provider: Provider = "gemini"
    discover_model: Optional[str] = None
    report_provider: Provider = "claude"
    report_model: Optional[str] = None

    locale: Literal["tr", "en"] = "tr"
    data_dir: Path = Path("data")
    beta_reference_file: Path = Path("betaemerg.xls")

    def _default_model(self, provider: Provider) -> str:
        return {
            "gemini": self.gemini_model,
            "claude": self.claude_model,
            "openai": self.openai_model,
        }[provider]

    def stage(self, name: Stage) -> tuple[Provider, str]:
        """Resolve the (provider, model) pair for a pipeline stage.

        Unset stage provider falls back to the global `llm_provider`; unset stage
        model falls back to the chosen provider's default model. This keeps a
        single global override (`FINAUTO_LLM_PROVIDER`) working while allowing
        fine-grained, per-stage routing (`FINAUTO_REPORT_PROVIDER=claude`, ...).
        """
        provider = getattr(self, f"{name}_provider") or self.llm_provider
        model = getattr(self, f"{name}_model") or self._default_model(provider)
        return provider, model


def get_settings() -> Settings:
    # Load .env into os.environ so the provider SDKs (google-genai reads
    # GEMINI_API_KEY, anthropic reads ANTHROPIC_API_KEY) can find their keys.
    load_dotenv()
    return Settings()
