from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tomlkit
from tomlkit.items import Table

from flosh.paths import default_config_path, default_state_path, expand_path

ConfigFormat = Literal["toml", "json", "text"]

DEFAULT_CONFIG: dict[str, Any] = {
    "capture": {
        "default_mode": "area",
        "default_destination": "clipboard",
        "filename_template": "%Y-%m-%d_%H-%M-%S.png",
        "save_dir": "~/Pictures/Screenshots",
        "editor": "swappy",
        "picker": "auto",
    },
    "target": {
        "root": "~/Pictures",
        "start": "current",
        "recent_limit": 20,
    },
    "paste": {
        "backend": "xdotool",
        "wait_s": 2.0,
        "delay_ms": 80,
        "restore_clipboard": False,
    },
    "ocr": {
        "lang": "deu+eng",
        "psm": 6,
        "preprocess": True,
        "keep_preprocessed": False,
    },
    "tools": {
        "grimshot": "grimshot",
        "grim": "grim",
        "slurp": "slurp",
        "swappy": "swappy",
        "wl_copy": "wl-copy",
        "wl_paste": "wl-paste",
        "xdotool": "xdotool",
        "wtype": "wtype",
        "ydotool": "ydotool",
        "tesseract": "tesseract",
        "magick": "magick",
    },
    "state": {
        "path": str(default_state_path()),
    },
}

ENV_OVERRIDES: dict[str, tuple[str, type[Any]]] = {
    "FLOSH_CAPTURE_SAVE_DIR": ("capture.save_dir", str),
    "FLOSH_CAPTURE_MODE": ("capture.default_mode", str),
    "FLOSH_CAPTURE_DESTINATION": ("capture.default_destination", str),
    "FLOSH_CAPTURE_EDITOR": ("capture.editor", str),
    "FLOSH_FILENAME_TEMPLATE": ("capture.filename_template", str),
    "FLOSH_TARGET_ROOT": ("target.root", str),
    "FLOSH_PICKER": ("capture.picker", str),
    "FLOSH_PASTE_BACKEND": ("paste.backend", str),
    "FLOSH_PASTE_WAIT_S": ("paste.wait_s", float),
    "FLOSH_PASTE_DELAY_MS": ("paste.delay_ms", int),
    "FLOSH_PASTE_RESTORE_CLIPBOARD": ("paste.restore_clipboard", bool),
    "FLOSH_OCR_LANG": ("ocr.lang", str),
    "FLOSH_OCR_PSM": ("ocr.psm", int),
    "FLOSH_OCR_PREPROCESS": ("ocr.preprocess", bool),
    "FLOSH_OCR_KEEP_PREPROCESSED": ("ocr.keep_preprocessed", bool),
    "FLOSH_STATE_PATH": ("state.path", str),
}


@dataclass(frozen=True)
class RuntimeContext:
    config_path: Path
    profile: str | None
    verbose: bool = False


@dataclass(frozen=True)
class ResolvedConfig:
    data: dict[str, Any]
    sources: dict[str, str]
    path: Path
    profile: str | None


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def coerce_value(value: str, target_type: type[Any]) -> Any:
    if target_type is bool:
        return parse_bool(value)
    return target_type(value)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def iter_leaf_paths(data: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key, value in data.items():
        current = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            paths.extend(iter_leaf_paths(value, current))
        else:
            paths.append(current)
    return paths


def get_dotted(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted)
        current = current[part]
    return current


def set_dotted(data: dict[str, Any], dotted: str, value: Any) -> None:
    current: dict[str, Any] = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        next_value = current.setdefault(part, {})
        if not isinstance(next_value, dict):
            raise ValueError(f"cannot set below non-table key: {part}")
        current = next_value
    current[parts[-1]] = value


def source_defaults(defaults: dict[str, Any]) -> dict[str, str]:
    return {path: "default" for path in iter_leaf_paths(defaults)}


def load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    return dict(doc)


def profile_data(raw_config: dict[str, Any], profile: str | None) -> dict[str, Any]:
    if not profile:
        return {}
    profiles = raw_config.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError(f"profile {profile!r} requested, but config has no [profiles] table")
    selected = profiles.get(profile)
    if not isinstance(selected, dict):
        raise ValueError(f"profile not found: {profile}")
    return dict(selected)


def strip_profiles(raw_config: dict[str, Any]) -> dict[str, Any]:
    raw = deepcopy(raw_config)
    raw.pop("profiles", None)
    return raw


def env_override_values(
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    env_map: Mapping[str, str] = os.environ if env is None else env
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for env_name, (path, target_type) in ENV_OVERRIDES.items():
        if env_name not in env_map:
            continue
        try:
            coerced = coerce_value(env_map[env_name], target_type)
        except ValueError as exc:
            raise ValueError(f"{env_name}: {exc}") from exc
        set_dotted(values, path, coerced)
        sources[path] = f"env:{env_name}"
    return values, sources


def resolve_config(ctx: RuntimeContext) -> ResolvedConfig:
    raw = load_config_file(ctx.config_path)
    file_config = strip_profiles(raw)
    selected_profile = profile_data(raw, ctx.profile)
    env_config, env_sources = env_override_values()

    data = deepcopy(DEFAULT_CONFIG)
    sources = source_defaults(DEFAULT_CONFIG)

    data = deep_merge(data, file_config)
    for path in iter_leaf_paths(file_config):
        sources[path] = f"config:{ctx.config_path}"

    if selected_profile:
        data = deep_merge(data, selected_profile)
        for path in iter_leaf_paths(selected_profile):
            sources[path] = f"profile:{ctx.profile}"

    data = deep_merge(data, env_config)
    sources.update(env_sources)

    return ResolvedConfig(data=data, sources=sources, path=ctx.config_path, profile=ctx.profile)


def default_config_document() -> str:
    doc = tomlkit.document()
    doc.add(tomlkit.comment("flosh configuration"))
    doc.add(tomlkit.comment("Precedence: CLI > environment > profile > config > defaults"))
    doc.add(tomlkit.nl())

    for section, values in DEFAULT_CONFIG.items():
        if section == "state":
            continue
        table = tomlkit.table()
        for key, value in values.items():
            table.add(key, value)
        doc.add(section, table)
        doc.add(tomlkit.nl())

    profiles = tomlkit.table()
    work = tomlkit.table()
    capture = tomlkit.table()
    capture.add("save_dir", "~/Work/PRIVATE/screenshots")
    work.add("capture", capture)
    profiles.add("work", work)
    doc.add("profiles", profiles)
    return tomlkit.dumps(doc)


def init_config(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_document(), encoding="utf-8")


def render_config(resolved: ResolvedConfig, fmt: ConfigFormat, *, include_sources: bool) -> str:
    if include_sources:
        lines = []
        for key in sorted(resolved.sources):
            try:
                value = get_dotted(resolved.data, key)
            except KeyError:
                continue
            lines.append(f"{key} = {value!r}\tsource={resolved.sources[key]}")
        return "\n".join(lines)

    if fmt == "json":
        return json.dumps(resolved.data, indent=2, sort_keys=True)
    if fmt == "toml":
        return tomlkit.dumps(dict_to_toml_doc(resolved.data))

    lines = []
    for key in sorted(iter_leaf_paths(resolved.data)):
        value = get_dotted(resolved.data, key)
        lines.append(f"{key} = {value!r}")
    return "\n".join(lines)


def dict_to_toml_doc(data: dict[str, Any]) -> tomlkit.TOMLDocument:
    doc = tomlkit.document()
    for key, value in data.items():
        if isinstance(value, dict):
            table = tomlkit.table()
            add_dict_to_table(table, value)
            doc.add(key, table)
        else:
            doc.add(key, value)
    return doc


def add_dict_to_table(table: Table, data: dict[str, Any]) -> None:
    for key, value in data.items():
        if isinstance(value, dict):
            child = tomlkit.table()
            add_dict_to_table(child, value)
            table.add(key, child)
        else:
            table.add(key, value)


def parse_cli_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false", "yes", "no", "on", "off"}:
        return parse_bool(value)
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def config_get(ctx: RuntimeContext, key: str) -> Any:
    resolved = resolve_config(ctx)
    return get_dotted(resolved.data, key)


def config_set(path: Path, key: str, value: str) -> None:
    data = (
        tomlkit.parse(path.read_text(encoding="utf-8"))
        if path.exists()
        else tomlkit.document()
    )

    parts = key.split(".")
    current: Any = data
    for part in parts[:-1]:
        if part not in current:
            current.add(part, tomlkit.table())
        current = current[part]
    current[parts[-1]] = parse_cli_value(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(data), encoding="utf-8")


def edit_config(path: Path) -> None:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(default_config_document(), encoding="utf-8")
    subprocess.run([editor, str(path)], check=True)


def make_runtime_context(
    *, config: str | Path | None, profile: str | None, verbose: bool
) -> RuntimeContext:
    config_path = expand_path(config) if config is not None else default_config_path()
    return RuntimeContext(config_path=config_path, profile=profile, verbose=verbose)
