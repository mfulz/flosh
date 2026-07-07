from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_path, user_state_path

APP_NAME = "flosh"


def default_config_path() -> Path:
    return user_config_path(APP_NAME) / "config.toml"


def default_state_path() -> Path:
    return user_state_path(APP_NAME) / "state.toml"


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser()
