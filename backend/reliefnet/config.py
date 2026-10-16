from functools import lru_cache
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    falkor_host: str = "localhost"
    falkor_port: int = 6379
    falkor_password: str | None = None

    # "auto" uses Claude when credentials exist, otherwise the rule-based mock.
    llm_mode: str = "auto"  # auto | claude | mock
    anthropic_api_key: str | None = None
    model_fast: str = "claude-haiku-5-5"
    model_smart: str = "claude-sonnet-5-5"
    llm_timeout_s: float = 60.0

    embed_mode: str = "auto"  # auto | fastembed | hash
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_dim: int = 384

    auth_mode: str = "dev"  # dev | clerk
    clerk_jwks_url: str | None = None
    clerk_issuer: str | None = None
    clerk_authorized_parties: str = ""  # comma separated origins

    telegram_bot_token: str | None = None
    telegram_bot_username: str | None = None

    # Demo-friendly timings. A real deployment would use longer leases.
    lease_ms: int = 8000
    poll_interval_s: float = 0.4
    dispatch_work_ms: int = 2000
    learner_interval_s: float = 40.0
    shift_times: str = "08:00,20:00"
    tz_offset_minutes: int = 330  # IST; lessons such as "after 4 pm" use local time

    dedupe_auto_merge: float = 0.78
    dedupe_ask_llm: float = 0.58
    near_radius_m: float = 450.0

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080"
    uploads_dir: str = "uploads"
    # slug:Display name pairs, created on startup.
    default_orgs: str = "redcross:Red Cross Ganga Nagar,local_ngo:Sahyog Local NGO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def anthropic_credentials_present() -> bool:
    return bool(
        get_settings().anthropic_api_key
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
