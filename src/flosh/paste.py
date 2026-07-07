from __future__ import annotations

import shlex
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
    newline: str
    pre_command: str | None
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


def paste_backend_settings(paste: dict[str, Any], backend_name: str) -> tuple[str, str, str | None]:
    backends = paste.get("backend", {})
    if not isinstance(backends, dict) or backend_name not in backends:
        raise ValueError(f"unsupported paste backend: {backend_name}")
    backend = backends[backend_name]
    if not isinstance(backend, dict):
        raise ValueError(f"paste.backend.{backend_name} must be a table")
    command = backend.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"paste.backend.{backend_name}.command needs a non-empty command")
    newline = str(backend.get("newline", "literal"))
    if newline not in {"literal", "xdotool-return"}:
        raise ValueError(f"unsupported paste.backend.{backend_name}.newline: {newline}")
    pre_command_raw = backend.get("pre_command")
    pre_command = str(pre_command_raw) if pre_command_raw is not None else None
    return command, newline, pre_command


def type_text(text: str, settings: PasteSettings) -> None:
    if settings.wait_s > 0:
        time.sleep(settings.wait_s)

    if not text:
        return

    values = {
        **settings.variables,
        "backend": settings.variables["backend"],
        "text": text,
        "delay_ms": str(settings.delay_ms),
        "action": settings.action,
        "backend_name": settings.backend_name,
    }
    if settings.newline == "xdotool-return" and any(ch in text for ch in "\n\r"):
        run_xdotool_return_text(text, settings=settings, values=values)
        return

    rendered = render_command_template(settings.command, values, raw_keys=settings.raw_variables)
    run_checked(rendered)


def run_xdotool_return_text(
    text: str,
    *,
    settings: PasteSettings,
    values: dict[str, str],
) -> None:
    if settings.pre_command:
        run_checked(
            render_command_template(settings.pre_command, values, raw_keys=settings.raw_variables)
        )

    xdotool = shlex.split(settings.variables.get("xdotool", "xdotool"))
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = normalized.split("\n")
    for index, part in enumerate(parts):
        if part:
            run_checked_argv(
                [
                    *xdotool,
                    "type",
                    "--clearmodifiers",
                    "--delay",
                    str(settings.delay_ms),
                    part,
                ]
            )
        if index < len(parts) - 1:
            run_checked_argv([*xdotool, "key", "Return"])


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


def run_checked_argv(cmd: list[str]) -> None:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or f"exit code {proc.returncode}"
        raise RuntimeError(f"paste command failed: {' '.join(cmd[:2])}: {details}")
