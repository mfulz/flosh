from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any

from flosh.capture import render_command_template


@dataclass(frozen=True)
class PasteSettings:
    action: str
    backend_name: str
    command: str
    wait_s: float
    delay_ms: int
    wl_paste: str
    variables: dict[str, str]
    raw_variables: set[str]


def read_clipboard(*, wl_paste: str) -> str:
    proc = subprocess.run(
        [wl_paste],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(stderr or f"clipboard read failed: {wl_paste}")
    return proc.stdout


def paste_action_command(paste: dict[str, Any], action: str) -> str:
    actions = paste.get("actions", {})
    if not isinstance(actions, dict) or action not in actions:
        raise ValueError(f"unsupported paste action: {action}; define paste.actions.{action}")
    command = actions[action]
    if isinstance(command, str) and command.strip():
        return command
    raise ValueError(f"paste.actions.{action} needs a non-empty command")


def paste_backend_command(paste: dict[str, Any], backend_name: str) -> str:
    backends = paste.get("backend", {})
    if not isinstance(backends, dict) or backend_name not in backends:
        raise ValueError(f"unsupported paste backend: {backend_name}")
    backend = backends[backend_name]
    if not isinstance(backend, dict):
        raise ValueError(f"paste.backend.{backend_name} must be a table")
    command = backend.get("command")
    if isinstance(command, str) and command.strip():
        return command
    raise ValueError(f"paste.backend.{backend_name}.command needs a non-empty command")


def type_text(text: str, settings: PasteSettings) -> None:
    if settings.wait_s > 0:
        time.sleep(settings.wait_s)

    if not text:
        return

    rendered = render_command_template(
        settings.command,
        {
            **settings.variables,
            "backend": settings.variables["backend"],
            "text": text,
            "delay_ms": str(settings.delay_ms),
            "action": settings.action,
            "backend_name": settings.backend_name,
        },
        raw_keys=settings.raw_variables,
    )
    run_checked(rendered)


def run_checked(command: str) -> None:
    proc = subprocess.run(
        command,
        shell=True,
        executable="/bin/sh",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or f"exit code {proc.returncode}"
        raise RuntimeError(f"paste command failed: {details}")
