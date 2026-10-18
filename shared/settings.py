"""Environment configuration for every mirava.ai service (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All env settings; secrets are `SecretStr` so they never appear in repr or logs."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["local", "cloud"] = "local"
    gcp_project_id: str = "your-project-id"
    gcp_region: str = "asia-south1"
    vertex_location: str = "global"

    llm_backend: Literal["fake", "openrouter", "vertex"] = "fake"
    decision_backend: Literal["fake", "openrouter"] = "fake"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_api_key_fallback: SecretStr = SecretStr("")  # used once the main key is out of credit / over its limit
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_title: str = "mirava.ai"
    engine_reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low"
    llm_concurrency: int = 32
    decision_batch_size: int = 32

    daily_cap_usd: float = 15.0
    interactive_cap_usd: float = 5.0

    world_agents: int = 1000
    world_seed: int = 4271
    world_seconds_per_sim_day: int = 3600
    world_map: str = "assets/maps/indiranagar.tmj"
    checkpoint_every_sim_minutes: int = 60
    engine_url: str = "http://localhost:8100"
    max_messages_per_person: int = 10
    stranger_max_messages_per_person: int = 4

    bq_backend: Literal["duckdb", "bigquery"] = "duckdb"
    bq_dataset: str = "mirava"
    duckdb_path: str = ".data/mirava.duckdb"
    analyst_sa: str = ""                    # cloud: read-only analyst SA impersonated by the api for Insights SQL
    firestore_emulator_host: str | None = "127.0.0.1:8080"
    gcs_bucket_uploads: str = ""
    gcs_bucket_worlds: str = ""
    gcs_bucket_exports: str = ""
    local_files_dir: str = ".data/files"
    pubsub_topic_events: str = "world-events"
    pubsub_topic_texts: str = "world-texts"
    event_sink: Literal["local", "pubsub"] = "local"
    store_backend: Literal["firestore", "memory"] = "firestore"
    engine_port: int = 8100
    engine_auth_audience: str = ""          # cloud: expected ID-token audience for POST /commands
    engine_allowed_callers: str = ""        # cloud: comma-separated service-account emails allowed to send commands
    world_speed: float = 1.0                # dev multiplier on top of seconds_per_sim_day

    model_armor_enabled: bool = False
    model_armor_template: str = ""

    llm_cache_dir: str = Field(default=".data/llm-cache")

    @property
    def has_openrouter_key(self) -> bool:
        """True when a non-empty OpenRouter key is configured."""
        return bool(self.openrouter_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
