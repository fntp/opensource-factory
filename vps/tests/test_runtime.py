"""运行目录自检模块单测（REQ-202610-0893）。"""
from __future__ import annotations

from pathlib import Path

from app.runtime import (
    REQUIRED_ENV_KEYS,
    SUBDIRS,
    check_runtime,
    main,
    parse_env_file,
    render_layout,
)


def _write_env(home: Path, overrides: dict[str, str] | None = None) -> Path:
    values = {key: "placeholder-value" for key in REQUIRED_ENV_KEYS}
    values["INTERNAL_TOKEN"] = "a" * 64
    values["CORS_ORIGINS"] = "http://localhost:5173"
    values["REDIS_URL"] = "redis://127.0.0.1:6379/0"
    if overrides:
        values.update(overrides)
    env_path = home / ".env"
    env_path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)
    return env_path


def _make_runtime(tmp_path: Path) -> Path:
    home = tmp_path / "openfactory"
    home.mkdir(mode=0o700)
    for name in SUBDIRS:
        (home / name).mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    _write_env(home)
    return home


def _by_name(results):
    return {item.name: item for item in results}


def test_check_runtime_all_green(tmp_path: Path) -> None:
    home = _make_runtime(tmp_path)
    results = check_runtime(home)
    assert all(item.ok for item in results), results
    assert "redis" not in _by_name(results)


def test_check_runtime_missing_home(tmp_path: Path) -> None:
    results = check_runtime(tmp_path / "missing")
    assert results[0].name == "home"
    assert not results[0].ok


def test_check_runtime_detects_missing_layout(tmp_path: Path) -> None:
    home = _make_runtime(tmp_path)
    (home / "backups").rmdir()
    result = _by_name(check_runtime(home))["layout"]
    assert not result.ok
    assert "backups" in result.detail


def test_check_runtime_detects_public_env_permissions(tmp_path: Path) -> None:
    home = _make_runtime(tmp_path)
    (home / ".env").chmod(0o644)
    result = _by_name(check_runtime(home))["env_permissions"]
    assert not result.ok


def test_check_runtime_detects_missing_env_key(tmp_path: Path) -> None:
    home = tmp_path / "openfactory"
    home.mkdir(mode=0o700)
    for name in SUBDIRS:
        (home / name).mkdir(parents=True, exist_ok=True)
    env_path = home / ".env"
    env_path.write_text("APP_NAME=OpenFactory\n", encoding="utf-8")
    env_path.chmod(0o600)
    result = _by_name(check_runtime(home))["env_keys"]
    assert not result.ok
    assert "DATABASE_URL" in result.detail


def test_check_runtime_detects_placeholder_values(tmp_path: Path) -> None:
    home = _make_runtime(tmp_path)
    _write_env(home, {"INTERNAL_TOKEN": "CHANGE_ME_TOKEN"})
    result = _by_name(check_runtime(home))["env_placeholders"]
    assert not result.ok
    assert "INTERNAL_TOKEN" in result.detail


def test_check_runtime_detects_short_internal_token(tmp_path: Path) -> None:
    home = _make_runtime(tmp_path)
    _write_env(home, {"INTERNAL_TOKEN": "short"})
    result = _by_name(check_runtime(home))["internal_token"]
    assert not result.ok


def test_parse_env_file_ignores_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# 注释\n\nAPP_NAME=OpenFactory\nLOG_DIR=/tmp/logs\n", encoding="utf-8")
    assert parse_env_file(path) == {"APP_NAME": "OpenFactory", "LOG_DIR": "/tmp/logs"}


def test_render_layout_lists_all_dirs(tmp_path: Path) -> None:
    home = _make_runtime(tmp_path)
    text = render_layout(home)
    for name in SUBDIRS:
        assert name in text
    assert ".env" in text


def test_cli_check_returns_zero_when_green(tmp_path: Path, capsys) -> None:
    home = _make_runtime(tmp_path)
    assert main(["check", "--home", str(home)]) == 0
    assert "FAIL" not in capsys.readouterr().out


def test_cli_check_returns_one_when_broken(tmp_path: Path) -> None:
    assert main(["check", "--home", str(tmp_path / "missing")]) == 1
