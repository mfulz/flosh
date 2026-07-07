from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

CaptureMode = str
CaptureDestination = Literal["clipboard", "file"]
CaptureEditor = Literal["satty", "swappy"]

MENU_EDITOR = "Edit/save in editor"
MENU_SAVE = "Save screenshot directly"
MENU_SELECT_DIR = "Select/change target directory"
MENU_CANCEL = "Cancel"


class CaptureCancelled(RuntimeError):
    """Raised when an interactive capture/editor flow is cancelled."""


@dataclass(frozen=True)
class CaptureCommandSettings:
    target_dir: Path
    mode: CaptureMode
    action: str
    backend_name: str
    frontend_name: str
    filename_template: str
    command: str
    destination: CaptureDestination
    variables: dict[str, str]
    raw_variables: set[str]


@dataclass(frozen=True)
class CaptureSettings:
    target_dir: Path
    mode: CaptureMode
    filename_template: str
    use_swappy: bool
    grimshot: str
    editor: CaptureEditor
    swappy: str
    satty: str
    wl_copy: str
    picker: str


def render_output_path(target_dir: Path, filename_template: str) -> Path:
    name = datetime.now().strftime(filename_template)
    if not name.strip():
        raise ValueError("filename template rendered an empty name")
    candidate = target_dir / name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 1000):
        deduped = candidate.with_name(f"{stem}_{index}{suffix}")
        if not deduped.exists():
            return deduped
    raise ValueError(f"could not find free output filename below: {target_dir}")



TEMPLATE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def command_for_action(capture: dict[str, Any], action: str) -> str:
    actions = capture.get("actions", {})
    if not isinstance(actions, dict) or action not in actions:
        raise ValueError(f"unsupported capture action: {action}; define capture.actions.{action}")
    command = actions[action]
    if isinstance(command, str) and command.strip():
        return command
    raise ValueError(f"capture.actions.{action} needs a non-empty command")


def command_for_backend_mode(capture: dict[str, Any], backend_name: str, mode: str) -> str:
    backends = capture.get("backend", {})
    if not isinstance(backends, dict) or backend_name not in backends:
        raise ValueError(f"unsupported capture backend: {backend_name}")
    backend = backends[backend_name]
    if not isinstance(backend, dict):
        raise ValueError(f"capture.backend.{backend_name} must be a table")
    command = backend.get(mode)
    if isinstance(command, str) and command.strip():
        return command
    raise ValueError(
        f"unsupported capture mode for backend {backend_name}: {mode}; "
        f"define capture.backend.{backend_name}.{mode}"
    )


def frontend_settings(
    capture: dict[str, Any],
    frontend_name: str,
) -> tuple[str, CaptureDestination | None]:
    frontends = capture.get("frontend", {})
    if not isinstance(frontends, dict) or frontend_name not in frontends:
        raise ValueError(f"unsupported capture frontend: {frontend_name}")
    frontend = frontends[frontend_name]
    if not isinstance(frontend, dict):
        raise ValueError(f"capture.frontend.{frontend_name} must be a table")
    command = frontend.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"capture.frontend.{frontend_name}.command needs a non-empty command")
    destination = frontend.get("destination")
    if destination is None:
        return command, None
    if destination == "clipboard":
        return command, "clipboard"
    if destination == "file":
        return command, "file"
    raise ValueError(f"unsupported capture.frontend.{frontend_name}.destination: {destination}")


def action_uses_frontend(command: str) -> bool:
    return "{{frontend}}" in command


def destination_for_capture(
    *,
    configured_default: str,
    frontend_destination: CaptureDestination | None,
    save: bool,
    clipboard: bool,
) -> CaptureDestination:
    if save and clipboard:
        raise ValueError("--save and --clipboard are mutually exclusive")
    if save:
        return "file"
    if clipboard:
        return "clipboard"
    if frontend_destination is not None:
        return frontend_destination
    if configured_default == "clipboard":
        return "clipboard"
    if configured_default == "file":
        return "file"
    raise ValueError(f"unsupported capture.default_destination: {configured_default}")


def run_capture_command(settings: CaptureCommandSettings) -> Path | None:
    settings.target_dir.mkdir(parents=True, exist_ok=True)
    output_path = render_output_path(settings.target_dir, settings.filename_template)
    values = {
        **settings.variables,
        "destination": str(output_path) if settings.destination == "file" else "-",
        "output": str(output_path),
        "output_path": str(output_path),
        "target_dir": str(settings.target_dir),
        "filename": output_path.name,
        "action": settings.action,
        "backend_name": settings.backend_name,
        "frontend_name": settings.frontend_name,
    }
    rendered = render_command_template(settings.command, values, raw_keys=settings.raw_variables)
    proc = subprocess.run(
        rendered,
        shell=True,
        executable="/bin/sh",
        env=capture_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        output_path.unlink(missing_ok=True)
        details = (proc.stderr or "").strip()
        raise RuntimeError(
            f"capture command failed with exit code {proc.returncode}: {details}"
            if details
            else f"capture command failed with exit code {proc.returncode}"
        )
    if settings.destination == "clipboard":
        return None
    if not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise CaptureCancelled("capture cancelled")
    return output_path


def render_command_template(
    template: str,
    values: dict[str, str],
    *,
    raw_keys: set[str] | None = None,
) -> str:
    return expand_template_value(template, values, stack=(), raw_keys=raw_keys or set())


def expand_template_value(
    template: str,
    values: dict[str, str],
    *,
    stack: tuple[str, ...],
    raw_keys: set[str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"unknown capture command template variable: {key}")
        if key in stack:
            cycle = " -> ".join((*stack, key))
            raise ValueError(f"recursive capture command template variable: {cycle}")
        value = values[key]
        if key in raw_keys:
            return expand_template_value(value, values, stack=(*stack, key), raw_keys=raw_keys)
        if TEMPLATE_PATTERN.search(value):
            expanded = expand_template_value(value, values, stack=(*stack, key), raw_keys=raw_keys)
            return shlex.quote(expanded)
        return shlex.quote(value)

    return TEMPLATE_PATTERN.sub(replace, template)


def capture_screenshot_to_file(settings: CaptureSettings) -> Path:
    settings.target_dir.mkdir(parents=True, exist_ok=True)
    output_path = render_output_path(settings.target_dir, settings.filename_template)
    try:
        run_checked([settings.grimshot, "save", settings.mode, str(output_path)], env=capture_env())
    except RuntimeError:
        output_path.unlink(missing_ok=True)
        raise
    reject_empty_capture(output_path)
    return output_path


def open_editor(settings: CaptureSettings) -> Path:
    raw_path = capture_raw_screenshot(grimshot=settings.grimshot, mode=settings.mode)
    try:
        return edit_raw_capture(
            raw_path,
            target_dir=settings.target_dir,
            filename_template=settings.filename_template,
            editor=settings.editor,
            swappy=settings.swappy,
            satty=settings.satty,
        )
    finally:
        raw_path.unlink(missing_ok=True)


def open_raw_in_editor(
    raw_path: Path,
    *,
    target_dir: Path,
    filename_template: str,
    editor: CaptureEditor,
    swappy: str,
    satty: str,
) -> Path:
    return edit_raw_capture(
        raw_path,
        target_dir=target_dir,
        filename_template=filename_template,
        editor=editor,
        swappy=swappy,
        satty=satty,
    )


def capture_screenshot_to_clipboard(settings: CaptureSettings) -> None:
    raw_path = capture_raw_screenshot(grimshot=settings.grimshot, mode=settings.mode)
    try:
        start_wl_copy(settings.wl_copy, raw_path)
    finally:
        raw_path.unlink(missing_ok=True)


def start_wl_copy(wl_copy: str, payload_path: Path) -> None:
    with payload_path.open("rb") as payload:
        subprocess.Popen(
            [wl_copy, "--type", "image/png"],
            stdin=payload,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def reject_empty_capture(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.unlink(missing_ok=True)
    raise RuntimeError("capture produced no image; treating it as cancelled")


def capture_raw_screenshot(*, grimshot: str, mode: CaptureMode) -> Path:
    with tempfile.NamedTemporaryFile(prefix="flosh-capture-", suffix=".png", delete=False) as tmp:
        raw_path = Path(tmp.name)
    try:
        run_checked([grimshot, "save", mode, str(raw_path)], env=capture_env())
        reject_empty_capture(raw_path)
    except RuntimeError:
        raw_path.unlink(missing_ok=True)
        raise
    return raw_path


def save_raw_capture(raw_path: Path, *, target_dir: Path, filename_template: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = render_output_path(target_dir, filename_template)
    shutil.copy2(raw_path, output_path)
    return output_path


def edit_raw_capture(
    raw_path: Path,
    *,
    target_dir: Path,
    filename_template: str,
    editor: CaptureEditor,
    swappy: str,
    satty: str,
) -> Path:
    if editor == "satty":
        return edit_raw_capture_satty(
            raw_path,
            target_dir=target_dir,
            filename_template=filename_template,
            satty=satty,
        )
    if editor == "swappy":
        return edit_raw_capture_swappy(raw_path, swappy=swappy)
    raise ValueError(f"unsupported capture editor: {editor}")


def edit_raw_capture_satty(
    raw_path: Path,
    *,
    target_dir: Path,
    filename_template: str,
    satty: str,
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = render_output_path(target_dir, filename_template)
    run_checked(
        [
            satty,
            "--filename",
            str(raw_path),
            "--output-filename",
            str(output_path),
            "--actions-on-escape",
            "exit",
            "--early-exit",
            "save",
        ],
        env=capture_env(),
    )
    if not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise CaptureCancelled("capture cancelled")
    return output_path


def edit_raw_capture_swappy(raw_path: Path, *, swappy: str) -> Path:
    run_checked([swappy, "-f", str(raw_path)], env=capture_env())
    raise RuntimeError(
        "swappy editor cannot report the saved output path reliably; "
        "use capture.editor=satty for flosh-managed saves"
    )


def capture_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("WLR_NO_HARDWARE_CURSORS", "1")
    return env


def run_checked(cmd: list[str], *, env: dict[str, str]) -> None:
    proc = subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        details = (proc.stderr or "").strip()
        base = f"command failed with exit code {proc.returncode}: {' '.join(cmd[:3])}"
        raise RuntimeError(f"{base}: {details}" if details else base)


def notify(summary: str, body: str = "") -> None:
    notify_send = shutil.which("notify-send")
    if not notify_send:
        return
    try:
        subprocess.run(
            [notify_send, summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return
