from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_WORK_ROOT = Path(
    os.getenv(
        "TOOLHUB_WORK_ROOT",
        "/home/shinku/data/service/tool/agent-tools-gateway/tool-work",
    )
)


def _default_input_roots() -> list[Path]:
    return [DEFAULT_WORK_ROOT / "input"]


def _default_output_roots() -> list[Path]:
    return [DEFAULT_WORK_ROOT / "output"]


def _split_paths(value: str) -> list[str]:
    if os.pathsep in value:
        return [part for part in value.split(os.pathsep) if part]
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    """Runtime settings.

    YAML is loaded explicitly by ``load_settings``; env vars use the
    ``TOOLHUB_`` prefix and intentionally override YAML values.
    """

    model_config = SettingsConfigDict(
        env_prefix="TOOLHUB_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    convertx_base_url: str = "http://127.0.0.1:3000"
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8766
    request_timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 30.0
    conversion_timeout_seconds: float = 600.0
    poll_interval_seconds: float = 1.0
    max_file_bytes: int = 512 * 1024 * 1024
    allowed_input_roots: list[Path] = Field(default_factory=_default_input_roots)
    allowed_output_roots: list[Path] = Field(default_factory=_default_output_roots)
    temp_root: Path = DEFAULT_WORK_ROOT / "tmp"
    auth_token: str | None = None

    @field_validator("allowed_input_roots", "allowed_output_roots", mode="before")
    @classmethod
    def _coerce_path_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _split_paths(value)
        return value

    def ensure_directories(self) -> None:
        for root in [*self.allowed_input_roots, *self.allowed_output_roots, self.temp_root]:
            root.expanduser().mkdir(parents=True, exist_ok=True)


class YamlSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    convertx_base_url: str | None = None
    api_host: str | None = None
    api_port: int | None = None
    mcp_host: str | None = None
    mcp_port: int | None = None
    request_timeout_seconds: float | None = None
    connect_timeout_seconds: float | None = None
    conversion_timeout_seconds: float | None = None
    poll_interval_seconds: float | None = None
    max_file_bytes: int | None = None
    allowed_input_roots: list[Path] | None = None
    allowed_output_roots: list[Path] | None = None
    temp_root: Path | None = None
    auth_token: str | None = None


def _read_yaml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {config_path}")
    parsed = YamlSettings.model_validate(raw)
    return parsed.model_dump(exclude_none=True)


def load_settings(config_path: str | Path | None = None) -> Settings:
    path = Path(
        config_path
        or os.getenv("TOOLHUB_CONFIG")
        or Path.cwd() / "config.yaml"
    ).expanduser()
    yaml_data = _read_yaml_config(path)

    # BaseSettings applies env values, but init values have priority. Build a
    # default/env instance first, then let explicitly configured YAML fill only
    # fields that env did not set.
    env_settings = Settings()
    env_names = {f"TOOLHUB_{name.upper()}" for name in Settings.model_fields}
    env_overrides = {name for name in Settings.model_fields if f"TOOLHUB_{name.upper()}" in os.environ}
    merged = env_settings.model_dump()
    for key, value in yaml_data.items():
        if key not in env_overrides:
            merged[key] = value

    settings = Settings.model_validate(merged)
    settings.ensure_directories()
    _ = env_names  # Keeps the supported env names obvious during maintenance.
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
