from __future__ import annotations

from pathlib import Path

from toolhub.config import load_settings, Settings
from toolhub.registry import get_enabled_backends


def _paths(root: Path) -> tuple[Path, Path, Path, Path]:
    work_root = root / "tools" / "ConvertX" / "work"
    input_root = work_root / "input"
    output_root = work_root / "output"
    temp_root = work_root / "tmp"
    return work_root, input_root, output_root, temp_root


def _webcapture_paths(root: Path) -> tuple[Path, Path, Path]:
    work_root = root / "tools" / "WebCapture" / "work"
    output_root = work_root / "output"
    temp_root = work_root / "tmp"
    return work_root, output_root, temp_root


def test_backend_scoped_convertx_config_is_used(tmp_path: Path) -> None:
    work_root, input_root, output_root, temp_root = _paths(tmp_path)
    settings = Settings(
        backends={
            "convertx": {
                "base_url": "http://scoped.test",
                "work_root": work_root,
                "allowed_input_roots": [input_root],
                "allowed_output_roots": [output_root],
                "temp_root": temp_root,
            }
        }
    )

    runtime = settings.convertx()

    assert runtime.base_url == "http://scoped.test"
    assert runtime.work_root == work_root
    assert runtime.allowed_input_roots == [input_root]
    assert runtime.allowed_output_roots == [output_root]
    assert runtime.temp_root == temp_root


def test_legacy_flat_convertx_config_still_works(tmp_path: Path) -> None:
    _work_root, input_root, output_root, temp_root = _paths(tmp_path)
    settings = Settings(
        convertx_base_url="http://legacy.test",
        allowed_input_roots=[input_root],
        allowed_output_roots=[output_root],
        temp_root=temp_root,
    )

    runtime = settings.convertx()

    assert runtime.base_url == "http://legacy.test"
    assert runtime.allowed_input_roots == [input_root]
    assert runtime.allowed_output_roots == [output_root]
    assert runtime.temp_root == temp_root


def test_backend_scoped_config_overrides_legacy_flat(tmp_path: Path) -> None:
    _legacy_work_root, legacy_input, legacy_output, legacy_temp = _paths(tmp_path / "legacy")
    work_root, input_root, output_root, temp_root = _paths(tmp_path / "scoped")
    settings = Settings(
        convertx_base_url="http://legacy.test",
        allowed_input_roots=[legacy_input],
        allowed_output_roots=[legacy_output],
        temp_root=legacy_temp,
        backends={
            "convertx": {
                "base_url": "http://scoped.test",
                "work_root": work_root,
                "allowed_input_roots": [input_root],
                "allowed_output_roots": [output_root],
                "temp_root": temp_root,
            }
        },
    )

    runtime = settings.convertx()

    assert runtime.base_url == "http://scoped.test"
    assert runtime.work_root == work_root
    assert runtime.allowed_input_roots == [input_root]
    assert runtime.allowed_output_roots == [output_root]
    assert runtime.temp_root == temp_root


def test_load_settings_reads_backend_scoped_env(monkeypatch, tmp_path: Path) -> None:
    work_root, input_root, output_root, temp_root = _paths(tmp_path / "env")
    config_path = tmp_path / "missing.yaml"
    monkeypatch.setenv("TOOLHUB_BACKENDS__CONVERTX__BASE_URL", "http://env.test")
    monkeypatch.setenv("TOOLHUB_BACKENDS__CONVERTX__WORK_ROOT", str(work_root))
    monkeypatch.setenv(
        "TOOLHUB_BACKENDS__CONVERTX__ALLOWED_INPUT_ROOTS",
        str(input_root),
    )
    monkeypatch.setenv(
        "TOOLHUB_BACKENDS__CONVERTX__ALLOWED_OUTPUT_ROOTS",
        str(output_root),
    )
    monkeypatch.setenv("TOOLHUB_BACKENDS__CONVERTX__TEMP_ROOT", str(temp_root))

    settings = load_settings(config_path)
    runtime = settings.convertx()

    assert runtime.base_url == "http://env.test"
    assert runtime.work_root == work_root
    assert runtime.allowed_input_roots == [input_root]
    assert runtime.allowed_output_roots == [output_root]
    assert runtime.temp_root == temp_root


def test_env_overrides_only_requested_backend_leaf(monkeypatch, tmp_path: Path) -> None:
    work_root, input_root, output_root, temp_root = _paths(tmp_path / "yaml")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "backends:",
                "  convertx:",
                "    enabled: true",
                '    base_url: "http://yaml.test"',
                f'    work_root: "{work_root}"',
                "    allowed_input_roots:",
                f'      - "{input_root}"',
                "    allowed_output_roots:",
                f'      - "{output_root}"',
                f'    temp_root: "{temp_root}"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOOLHUB_BACKENDS__CONVERTX__BASE_URL", "http://env.test")

    settings = load_settings(config_path)
    runtime = settings.convertx()

    assert runtime.base_url == "http://env.test"
    assert runtime.work_root == work_root
    assert runtime.allowed_input_roots == [input_root]
    assert runtime.allowed_output_roots == [output_root]
    assert runtime.temp_root == temp_root


def test_env_partial_override_does_not_reenable_disabled_backend(monkeypatch, tmp_path: Path) -> None:
    work_root, input_root, output_root, temp_root = _paths(tmp_path / "yaml-disabled")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "backends:",
                "  convertx:",
                "    enabled: false",
                '    base_url: "http://yaml.test"',
                f'    work_root: "{work_root}"',
                "    allowed_input_roots:",
                f'      - "{input_root}"',
                "    allowed_output_roots:",
                f'      - "{output_root}"',
                f'    temp_root: "{temp_root}"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOOLHUB_BACKENDS__CONVERTX__BASE_URL", "http://env.test")

    settings = load_settings(config_path)

    assert settings.convertx().enabled is False
    assert get_enabled_backends(settings) == []


def test_env_path_lists_accept_json_style_strings(monkeypatch, tmp_path: Path) -> None:
    work_root, input_root, output_root, temp_root = _paths(tmp_path / "env-json")
    config_path = tmp_path / "missing.yaml"
    monkeypatch.setenv("TOOLHUB_BACKENDS__CONVERTX__WORK_ROOT", str(work_root))
    monkeypatch.setenv(
        "TOOLHUB_BACKENDS__CONVERTX__ALLOWED_INPUT_ROOTS",
        f'["{input_root}"]',
    )
    monkeypatch.setenv(
        "TOOLHUB_BACKENDS__CONVERTX__ALLOWED_OUTPUT_ROOTS",
        f'["{output_root}"]',
    )
    monkeypatch.setenv("TOOLHUB_BACKENDS__CONVERTX__TEMP_ROOT", str(temp_root))

    settings = load_settings(config_path)
    runtime = settings.convertx()

    assert runtime.allowed_input_roots == [input_root]
    assert runtime.allowed_output_roots == [output_root]


def test_webcapture_backend_defaults_to_disabled() -> None:
    settings = Settings()

    runtime = settings.webcapture()

    assert runtime.enabled is False


def test_backend_scoped_webcapture_config_is_used(tmp_path: Path) -> None:
    work_root, output_root, temp_root = _webcapture_paths(tmp_path)
    settings = Settings(
        backends={
            "webcapture": {
                "enabled": True,
                "base_url": "http://browserless.test",
                "token": "secret-token",
                "work_root": work_root,
                "allowed_output_roots": [output_root],
                "temp_root": temp_root,
                "browser_timeout_seconds": 90,
                "post_load_wait_ms": 250,
                "viewport_width": 1200,
                "viewport_height": 900,
                "pdf_format": "Letter",
                "block_private_networks": False,
            }
        }
    )

    runtime = settings.webcapture()

    assert runtime.enabled is True
    assert runtime.base_url == "http://browserless.test"
    assert runtime.token == "secret-token"
    assert runtime.work_root == work_root
    assert runtime.allowed_output_roots == [output_root]
    assert runtime.temp_root == temp_root
    assert runtime.browser_timeout_seconds == 90
    assert runtime.post_load_wait_ms == 250
    assert runtime.viewport_width == 1200
    assert runtime.viewport_height == 900
    assert runtime.pdf_format == "Letter"
    assert runtime.block_private_networks is False


def test_load_settings_reads_webcapture_env(monkeypatch, tmp_path: Path) -> None:
    work_root, output_root, temp_root = _webcapture_paths(tmp_path / "env")
    config_path = tmp_path / "missing.yaml"
    monkeypatch.setenv("TOOLHUB_BACKENDS__WEBCAPTURE__ENABLED", "true")
    monkeypatch.setenv("TOOLHUB_BACKENDS__WEBCAPTURE__BASE_URL", "http://browserless.test")
    monkeypatch.setenv("TOOLHUB_BACKENDS__WEBCAPTURE__TOKEN", "secret-token")
    monkeypatch.setenv("TOOLHUB_BACKENDS__WEBCAPTURE__WORK_ROOT", str(work_root))
    monkeypatch.setenv(
        "TOOLHUB_BACKENDS__WEBCAPTURE__ALLOWED_OUTPUT_ROOTS",
        f'["{output_root}"]',
    )
    monkeypatch.setenv("TOOLHUB_BACKENDS__WEBCAPTURE__TEMP_ROOT", str(temp_root))
    monkeypatch.setenv("TOOLHUB_BACKENDS__WEBCAPTURE__VIEWPORT_WIDTH", "1600")

    settings = load_settings(config_path)
    runtime = settings.webcapture()

    assert runtime.enabled is True
    assert runtime.base_url == "http://browserless.test"
    assert runtime.token == "secret-token"
    assert runtime.work_root == work_root
    assert runtime.allowed_output_roots == [output_root]
    assert runtime.temp_root == temp_root
    assert runtime.viewport_width == 1600


def test_webcapture_enabled_creates_directories(tmp_path: Path) -> None:
    work_root, output_root, temp_root = _webcapture_paths(tmp_path / "dirs")
    settings = Settings(
        backends={
            "webcapture": {
                "enabled": True,
                "work_root": work_root,
                "allowed_output_roots": [output_root],
                "temp_root": temp_root,
            }
        }
    )

    settings.ensure_directories()

    assert work_root.is_dir()
    assert output_root.is_dir()
    assert temp_root.is_dir()
