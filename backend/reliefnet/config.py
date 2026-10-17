from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    falkor_host: str = "localhost"
    falkor_port: int = 6379
    falkor_password: str | None = None

    # "auto" uses the configured models when their credentials exist, otherwise
    # the rule-based fallback. "live" always calls the models; "mock" never does.
    llm_mode: str = "auto"  # auto | live | mock
    # "provider:model", any provider LangChain's init_chat_model supports.
    model_fast: str = "anthropic:claude-haiku-5-5"
    model_smart: str = "anthropic:claude-sonnet-5-5"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
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

    # The place the region graph describes; see reliefnet/areas. Changing it needs `seed --reset`.
    area: str = "patna"
    # Optional. Without a key the dashboard draws its own chart instead of a Google map.
    google_maps_api_key: str | None = None

    cors_origins: str ="http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080"
    uploads_dir: str = "uploads"
    # slug:Display name pairs, created on startup.
    default_orgs: str = "redcross:Red Cross Patna,local_ngo:Sahyog Local NGO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
