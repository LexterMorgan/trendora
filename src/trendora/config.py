"""Environment-driven application settings. No secrets belong in code."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and optional `.env`."""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="trendora", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(alias="DATABASE_URL")
    youtube_api_key: str | None = Field(default=None, alias="YOUTUBE_API_KEY")
    youtube_channel_ids: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        alias="YOUTUBE_CHANNEL_IDS",
    )
    youtube_max_videos_per_channel: int = Field(
        default=50,
        ge=1,
        le=500,
        alias="YOUTUBE_MAX_VIDEOS_PER_CHANNEL",
    )
    meta_access_token: str | None = Field(default=None, alias="META_ACCESS_TOKEN")
    meta_graph_api_version: str | None = Field(default=None, alias="META_GRAPH_API_VERSION")
    stackexchange_api_key: str | None = Field(default=None, alias="STACKEXCHANGE_API_KEY")
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_repositories: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        alias="GITHUB_REPOSITORIES",
    )
    ai_provider: str | None = Field(default=None, alias="TRENDORA_AI_PROVIDER")
    ai_model: str | None = Field(default=None, alias="TRENDORA_AI_MODEL")
    ai_endpoint_url: str | None = Field(default=None, alias="TRENDORA_AI_ENDPOINT_URL")
    ai_api_key: str | None = Field(default=None, alias="TRENDORA_AI_API_KEY")

    @field_validator("database_url")
    @classmethod
    def normalize_postgres_url(cls, value: str) -> str:
        url = value.strip()
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgres://")
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL "
                "(postgresql+psycopg://, postgresql://, or postgres://)"
            )
        return url

    @field_validator(
        "youtube_api_key",
        "meta_access_token",
        "meta_graph_api_version",
        "stackexchange_api_key",
        "github_token",
        "ai_provider",
        "ai_model",
        "ai_endpoint_url",
        "ai_api_key",
        mode="before",
    )
    @classmethod
    def blank_optional_key_to_none(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("youtube_channel_ids", mode="before")
    @classmethod
    def parse_youtube_channel_ids(cls, value: object) -> list[str]:
        """Turn comma-separated YOUTUBE_CHANNEL_IDS into unique UC… IDs."""
        from trendora.connectors.youtube.exceptions import InvalidYouTubeWatchlistError
        from trendora.connectors.youtube.watchlist import parse_channel_ids

        try:
            return list(parse_channel_ids(value if value is not None else ()))
        except InvalidYouTubeWatchlistError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("github_repositories", mode="before")
    @classmethod
    def parse_github_repositories(cls, value: object) -> list[str]:
        """Turn comma-separated GITHUB_REPOSITORIES into unique owner/repo ids."""
        from trendora.connectors.github.exceptions import GitHubConfigurationError
        from trendora.connectors.github.connector import parse_repositories

        try:
            return list(parse_repositories(value if value is not None else ()))
        except GitHubConfigurationError as exc:
            raise ValueError(str(exc)) from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
