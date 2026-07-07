from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Literal

Backend = Literal["xdotool", "wtype", "ydotool"]
Keymap = Literal["none", "de-us"]


@dataclass(frozen=True)
class PasteSettings:
    backend: Backend
    keymap: Keymap
    wait_s: float
    delay_ms: int
    wl_paste: str
    xdotool: str
    wtype: str
    ydotool: str


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


def type_text(text: str, settings: PasteSettings) -> None:
    if settings.wait_s > 0:
        time.sleep(settings.wait_s)

    if not text:
        return

    if settings.backend == "xdotool":
        run_xdotool_type(apply_keymap(text, settings.keymap), settings)
        return
    if settings.backend == "wtype":
        run_wtype(text, settings)
        return
    if settings.backend == "ydotool":
        run_ydotool_type(text, settings)
        return
    raise ValueError(f"unsupported paste backend: {settings.backend}")


def apply_keymap(text: str, keymap: Keymap) -> str:
    if keymap == "none":
        return text
    if keymap == "de-us":
        return text.translate(str.maketrans("yzYZ", "zyZY"))
    raise ValueError(f"unsupported paste keymap: {keymap}")


def run_xdotool_type(text: str, settings: PasteSettings) -> None:
    cmd = [
        settings.xdotool,
        "type",
        "--clearmodifiers",
        "--delay",
        str(settings.delay_ms),
        "--",
        text,
    ]
    run_checked(cmd, input_text=None)


def run_wtype(text: str, settings: PasteSettings) -> None:
    cmd = [settings.wtype, "-d", str(settings.delay_ms), "-"]
    run_checked(cmd, input_text=text)


def run_ydotool_type(text: str, settings: PasteSettings) -> None:
    # ydotool operates on the evdev/uinput layer. Its CLI has changed over time;
    # keep this conservative and explicit instead of pretending it is as stable as xdotool.
    cmd = [settings.ydotool, "type", "--delay", str(settings.delay_ms), text]
    run_checked(cmd, input_text=None)


def run_checked(cmd: list[str], *, input_text: str | None) -> None:
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or f"exit code {proc.returncode}"
        raise RuntimeError(f"command failed: {' '.join(cmd[:2])}: {details}")
