from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit

from flosh.config import ResolvedConfig, get_dotted


@dataclass(frozen=True)
class FloshState:
    target_dir: str | None = None
    recent_targets: tuple[str, ...] = ()


def state_path(config: ResolvedConfig) -> Path:
    raw = get_dotted(config.data, "state.path")
    return Path(str(raw)).expanduser()


def load_state(path: Path) -> FloshState:
    if not path.exists():
        return FloshState()
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    target_dir = doc.get("target_dir")
    recent_raw = doc.get("recent_targets", [])
    recent = tuple(str(item) for item in recent_raw) if isinstance(recent_raw, list) else ()
    return FloshState(target_dir=str(target_dir) if target_dir else None, recent_targets=recent)


def write_state(path: Path, state: FloshState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = tomlkit.document()
    if state.target_dir is not None:
        doc.add("target_dir", state.target_dir)
    doc.add("recent_targets", list(state.recent_targets))
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def update_target(path: Path, target: Path, *, recent_limit: int) -> None:
    current = load_state(path)
    target_str = str(target)
    recent = [target_str]
    for item in current.recent_targets:
        if item != target_str:
            recent.append(item)
    write_state(
        path,
        FloshState(target_dir=target_str, recent_targets=tuple(recent[: max(recent_limit, 0)])),
    )


def effective_target(config: ResolvedConfig) -> Path:
    st = load_state(state_path(config))
    if st.target_dir:
        return Path(st.target_dir).expanduser()
    return Path(str(get_dotted(config.data, "capture.save_dir"))).expanduser()


def target_root(config: ResolvedConfig) -> Path:
    return Path(str(get_dotted(config.data, "target.root"))).expanduser()


def recent_limit(config: ResolvedConfig) -> int:
    value: Any = get_dotted(config.data, "target.recent_limit")
    return int(value)
