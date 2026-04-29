from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, get_args, get_origin

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .tools.searxng.models import normalize_safe_search


DEFAULT_GATEWAY_ROOT = Path(
    os.getenv("TOOLHUB_ROOT", "/home/shinku/data/service/tool/agent-tools-gateway")
)
DEFAULT_TOOLS_ROOT = DEFAULT_GATEWAY_ROOT / "tools"
DEFAULT_CONVERTX_HOME = DEFAULT_TOOLS_ROOT / "ConvertX"
DEFAULT_CONVERTX_WORK_ROOT = DEFAULT_CONVERTX_HOME / "work"
DEFAULT_DOCLING_HOME = DEFAULT_TOOLS_ROOT / "Docling"
DEFAULT_DOCLING_WORK_ROOT = DEFAULT_DOCLING_HOME / "work"
DEFAULT_WEBCAPTURE_HOME = DEFAULT_TOOLS_ROOT / "WebCapture"
DEFAULT_WEBCAPTURE_WORK_ROOT = DEFAULT_WEBCAPTURE_HOME / "work"
DEFAULT_SEARXNG_HOME = DEFAULT_TOOLS_ROOT / "SearXNG"


def _split_paths(value: str) -> list[str]:
    if os.pathsep in value:
        return [part for part in value.split(os.pathsep) if part]
    return [part.strip() for part in value.split(",") if part.strip()]


def _coerce_path_list(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") or stripped.startswith("-"):
            parsed = yaml.safe_load(stripped)
            if isinstance(parsed, list):
                return parsed
        return _split_paths(value)
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = get_origin(annotation)
    if origin is None:
        return None
    for arg in get_args(annotation):
        if arg is None or arg is type(None):
            continue
        nested = _nested_model(arg)
        if nested is not None:
            return nested
    return None


def _field_name(model: type[BaseModel], segment: str) -> str | None:
    normalized = segment.lower()
    if normalized in model.model_fields:
        return normalized
    lookup = {name.upper(): name for name in model.model_fields}
    return lookup.get(segment.upper())


def _resolve_env_path(model: type[BaseModel], raw_key: str) -> list[str] | None:
    delimiter = Settings.model_config.get("env_nested_delimiter", "__")
    raw_segments = raw_key.split(delimiter) if delimiter and delimiter in raw_key else [raw_key]

    path: list[str] = []
    current_model: type[BaseModel] | None = model
    for index, segment in enumerate(raw_segments):
        if current_model is None:
            return None
        field_name = _field_name(current_model, segment)
        if field_name is None:
            return None
        path.append(field_name)
        if index == len(raw_segments) - 1:
            return path
        field = current_model.model_fields[field_name]
        current_model = _nested_model(field.annotation)
    return path


def _assign_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    cursor = target
    for segment in path[:-1]:
        child = cursor.get(segment)
        if not isinstance(child, dict):
            child = {}
            cursor[segment] = child
        cursor = child
    cursor[path[-1]] = value


def _read_env_overrides() -> dict[str, Any]:
    prefix = Settings.model_config.get("env_prefix", "")
    overrides: dict[str, Any] = {}
    for key, value in os.environ.items():
        if prefix and not key.startswith(prefix):
            continue
        raw_key = key[len(prefix):] if prefix else key
        path = _resolve_env_path(Settings, raw_key)
        if path is None:
            continue
        _assign_nested(overrides, path, value)
    return overrides


class ConvertXBackendConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    base_url: str | None = None
    work_root: Path | None = None
    allowed_input_roots: list[Path] | None = None
    allowed_output_roots: list[Path] | None = None
    temp_root: Path | None = None

    @field_validator("allowed_input_roots", "allowed_output_roots", mode="before")
    @classmethod
    def _coerce_path_lists(cls, value: Any) -> Any:
        return _coerce_path_list(value)


class WebCaptureBackendConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    base_url: str | None = None
    token: str | None = None
    work_root: Path | None = None
    allowed_output_roots: list[Path] | None = None
    temp_root: Path | None = None
    browser_timeout_seconds: float | None = None
    post_load_wait_ms: int | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    pdf_format: str | None = None
    block_private_networks: bool | None = None
    max_capture_bytes: int | None = None
    max_full_page_height_px: int | None = None

    @field_validator("allowed_output_roots", mode="before")
    @classmethod
    def _coerce_path_lists(cls, value: Any) -> Any:
        return _coerce_path_list(value)


class DoclingBackendConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    base_url: str | None = None
    api_key: str | None = None
    work_root: Path | None = None
    allowed_input_roots: list[Path] | None = None
    allowed_output_roots: list[Path] | None = None
    temp_root: Path | None = None

    @field_validator("allowed_input_roots", "allowed_output_roots", mode="before")
    @classmethod
    def _coerce_path_lists(cls, value: Any) -> Any:
        return _coerce_path_list(value)


class SearXNGBackendConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    base_url: str | None = None
    default_limit: int | None = None
    max_limit: int | None = None
    default_language: str | None = None
    default_safe_search: str | None = None

    @field_validator("default_limit", "max_limit")
    @classmethod
    def _validate_positive_ints(cls, value: int | None, info) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return value

    @field_validator("default_safe_search")
    @classmethod
    def _validate_safe_search(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_safe_search(value)


class BackendsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    convertx: ConvertXBackendConfig = Field(default_factory=ConvertXBackendConfig)
    docling: DoclingBackendConfig = Field(default_factory=DoclingBackendConfig)
    searxng: SearXNGBackendConfig = Field(default_factory=SearXNGBackendConfig)
    webcapture: WebCaptureBackendConfig = Field(default_factory=WebCaptureBackendConfig)


class ConvertXRuntimeSettings(BaseModel):
    enabled: bool = True
    base_url: str = "http://127.0.0.1:3000"
    work_root: Path = DEFAULT_CONVERTX_WORK_ROOT
    allowed_input_roots: list[Path] = Field(
        default_factory=lambda: [DEFAULT_CONVERTX_WORK_ROOT / "input"]
    )
    allowed_output_roots: list[Path] = Field(
        default_factory=lambda: [DEFAULT_CONVERTX_WORK_ROOT / "output"]
    )
    temp_root: Path = DEFAULT_CONVERTX_WORK_ROOT / "tmp"
    request_timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 30.0
    conversion_timeout_seconds: float = 600.0
    poll_interval_seconds: float = 1.0
    max_file_bytes: int = 512 * 1024 * 1024

    def ensure_directories(self) -> None:
        self.work_root.expanduser().mkdir(parents=True, exist_ok=True)
        for root in [*self.allowed_input_roots, *self.allowed_output_roots, self.temp_root]:
            root.expanduser().mkdir(parents=True, exist_ok=True)


class WebCaptureRuntimeSettings(BaseModel):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:3001"
    token: str | None = None
    work_root: Path = DEFAULT_WEBCAPTURE_WORK_ROOT
    allowed_output_roots: list[Path] = Field(
        default_factory=lambda: [DEFAULT_WEBCAPTURE_WORK_ROOT / "output"]
    )
    temp_root: Path = DEFAULT_WEBCAPTURE_WORK_ROOT / "tmp"
    request_timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 30.0
    browser_timeout_seconds: float = 120.0
    post_load_wait_ms: int = 1000
    viewport_width: int = 1440
    viewport_height: int = 1024
    pdf_format: str = "A4"
    block_private_networks: bool = True
    max_capture_bytes: int = 64 * 1024 * 1024
    max_full_page_height_px: int = 20_000

    def ensure_directories(self) -> None:
        self.work_root.expanduser().mkdir(parents=True, exist_ok=True)
        for root in [*self.allowed_output_roots, self.temp_root]:
            root.expanduser().mkdir(parents=True, exist_ok=True)


class DoclingRuntimeSettings(BaseModel):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:5001"
    api_key: str | None = None
    work_root: Path = DEFAULT_DOCLING_WORK_ROOT
    allowed_input_roots: list[Path] = Field(
        default_factory=lambda: [DEFAULT_DOCLING_WORK_ROOT / "input"]
    )
    allowed_output_roots: list[Path] = Field(
        default_factory=lambda: [DEFAULT_DOCLING_WORK_ROOT / "output"]
    )
    temp_root: Path = DEFAULT_DOCLING_WORK_ROOT / "tmp"
    request_timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 30.0
    conversion_timeout_seconds: float = 600.0
    poll_interval_seconds: float = 1.0
    max_file_bytes: int = 512 * 1024 * 1024

    def ensure_directories(self) -> None:
        self.work_root.expanduser().mkdir(parents=True, exist_ok=True)
        for root in [*self.allowed_input_roots, *self.allowed_output_roots, self.temp_root]:
            root.expanduser().mkdir(parents=True, exist_ok=True)


class SearXNGRuntimeSettings(BaseModel):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080"
    default_limit: int = Field(default=5, gt=0)
    max_limit: int = Field(default=10, gt=0)
    default_language: str = "auto"
    default_safe_search: str = "moderate"
    request_timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 30.0

    @field_validator("default_safe_search")
    @classmethod
    def _validate_safe_search(cls, value: str) -> str:
        return normalize_safe_search(value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOOLHUB_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    api_host: str = "127.0.0.1"
    api_port: int = 8765
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8766
    request_timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 30.0
    conversion_timeout_seconds: float = 600.0
    poll_interval_seconds: float = 1.0
    max_file_bytes: int = 512 * 1024 * 1024
    auth_token: str | None = None
    backends: BackendsConfig = Field(default_factory=BackendsConfig)

    # Legacy flat ConvertX config fields, kept for compatibility.
    convertx_base_url: str | None = None
    allowed_input_roots: list[Path] | None = None
    allowed_output_roots: list[Path] | None = None
    temp_root: Path | None = None

    @field_validator("allowed_input_roots", "allowed_output_roots", mode="before")
    @classmethod
    def _coerce_legacy_path_lists(cls, value: Any) -> Any:
        return _coerce_path_list(value)

    def convertx(self) -> ConvertXRuntimeSettings:
        backend = self.backends.convertx

        work_root = backend.work_root or DEFAULT_CONVERTX_WORK_ROOT
        base_url = self.convertx_base_url or "http://127.0.0.1:3000"
        allowed_input_roots = self.allowed_input_roots or [work_root / "input"]
        allowed_output_roots = self.allowed_output_roots or [work_root / "output"]
        temp_root = self.temp_root or work_root / "tmp"

        if backend.base_url is not None:
            base_url = backend.base_url
        if backend.allowed_input_roots is not None:
            allowed_input_roots = backend.allowed_input_roots
        if backend.allowed_output_roots is not None:
            allowed_output_roots = backend.allowed_output_roots
        if backend.temp_root is not None:
            temp_root = backend.temp_root

        runtime = ConvertXRuntimeSettings(
            enabled=backend.enabled,
            base_url=base_url,
            work_root=work_root,
            allowed_input_roots=allowed_input_roots,
            allowed_output_roots=allowed_output_roots,
            temp_root=temp_root,
            request_timeout_seconds=self.request_timeout_seconds,
            connect_timeout_seconds=self.connect_timeout_seconds,
            conversion_timeout_seconds=self.conversion_timeout_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
            max_file_bytes=self.max_file_bytes,
        )
        if runtime.enabled:
            runtime.ensure_directories()
        return runtime

    def webcapture(self) -> WebCaptureRuntimeSettings:
        backend = self.backends.webcapture

        work_root = backend.work_root or DEFAULT_WEBCAPTURE_WORK_ROOT
        allowed_output_roots = backend.allowed_output_roots or [work_root / "output"]
        temp_root = backend.temp_root or work_root / "tmp"

        runtime = WebCaptureRuntimeSettings(
            enabled=backend.enabled,
            base_url=backend.base_url or "http://127.0.0.1:3001",
            token=backend.token,
            work_root=work_root,
            allowed_output_roots=allowed_output_roots,
            temp_root=temp_root,
            request_timeout_seconds=self.request_timeout_seconds,
            connect_timeout_seconds=self.connect_timeout_seconds,
            browser_timeout_seconds=(
                backend.browser_timeout_seconds
                if backend.browser_timeout_seconds is not None
                else 120.0
            ),
            post_load_wait_ms=(
                backend.post_load_wait_ms if backend.post_load_wait_ms is not None else 1000
            ),
            viewport_width=backend.viewport_width if backend.viewport_width is not None else 1440,
            viewport_height=(
                backend.viewport_height if backend.viewport_height is not None else 1024
            ),
            pdf_format=backend.pdf_format if backend.pdf_format is not None else "A4",
            block_private_networks=(
                backend.block_private_networks
                if backend.block_private_networks is not None
                else True
            ),
            max_capture_bytes=(
                backend.max_capture_bytes
                if backend.max_capture_bytes is not None
                else 64 * 1024 * 1024
            ),
            max_full_page_height_px=(
                backend.max_full_page_height_px
                if backend.max_full_page_height_px is not None
                else 20_000
            ),
        )
        if runtime.enabled:
            runtime.ensure_directories()
        return runtime

    def docling(self) -> DoclingRuntimeSettings:
        backend = self.backends.docling

        work_root = backend.work_root or DEFAULT_DOCLING_WORK_ROOT
        allowed_input_roots = backend.allowed_input_roots or [work_root / "input"]
        allowed_output_roots = backend.allowed_output_roots or [work_root / "output"]
        temp_root = backend.temp_root or work_root / "tmp"

        runtime = DoclingRuntimeSettings(
            enabled=backend.enabled,
            base_url=backend.base_url or "http://127.0.0.1:5001",
            api_key=backend.api_key,
            work_root=work_root,
            allowed_input_roots=allowed_input_roots,
            allowed_output_roots=allowed_output_roots,
            temp_root=temp_root,
            request_timeout_seconds=self.request_timeout_seconds,
            connect_timeout_seconds=self.connect_timeout_seconds,
            conversion_timeout_seconds=self.conversion_timeout_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
            max_file_bytes=self.max_file_bytes,
        )
        if runtime.enabled:
            runtime.ensure_directories()
        return runtime

    def searxng(self) -> SearXNGRuntimeSettings:
        backend = self.backends.searxng

        return SearXNGRuntimeSettings(
            enabled=backend.enabled,
            base_url=backend.base_url or "http://127.0.0.1:8080",
            default_limit=backend.default_limit if backend.default_limit is not None else 5,
            max_limit=backend.max_limit if backend.max_limit is not None else 10,
            default_language=backend.default_language or "auto",
            default_safe_search=backend.default_safe_search or "moderate",
            request_timeout_seconds=self.request_timeout_seconds,
            connect_timeout_seconds=self.connect_timeout_seconds,
        )

    def ensure_directories(self) -> None:
        if self.backends.convertx.enabled:
            self.convertx().ensure_directories()
        if self.backends.docling.enabled:
            self.docling().ensure_directories()
        if self.backends.webcapture.enabled:
            self.webcapture().ensure_directories()


class YamlSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_host: str | None = None
    api_port: int | None = None
    mcp_host: str | None = None
    mcp_port: int | None = None
    request_timeout_seconds: float | None = None
    connect_timeout_seconds: float | None = None
    conversion_timeout_seconds: float | None = None
    poll_interval_seconds: float | None = None
    max_file_bytes: int | None = None
    auth_token: str | None = None
    backends: BackendsConfig | None = None
    convertx_base_url: str | None = None
    allowed_input_roots: list[Path] | None = None
    allowed_output_roots: list[Path] | None = None
    temp_root: Path | None = None

    @field_validator("allowed_input_roots", "allowed_output_roots", mode="before")
    @classmethod
    def _coerce_legacy_path_lists(cls, value: Any) -> Any:
        return _coerce_path_list(value)


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
        config_path or os.getenv("TOOLHUB_CONFIG") or Path.cwd() / "config.yaml"
    ).expanduser()
    yaml_data = _read_yaml_config(path)
    env_data = _read_env_overrides()
    merged = _deep_merge(yaml_data, env_data)
    settings = Settings.model_validate(merged)
    settings.ensure_directories()
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
