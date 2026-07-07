from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

CaptureMode = Literal["area", "screen", "output", "active", "window"]
CaptureDestination = Literal["clipboard", "file"]

MENU_SWAPPY = "Edit/save in swappy"
MENU_SAVE = "Save screenshot directly"
MENU_SELECT_DIR = "Select/change target directory"
MENU_CANCEL = "Cancel"


@dataclass(frozen=True)
class CaptureSettings:
    target_dir: Path
    mode: CaptureMode
    filename_template: str
    use_swappy: bool
    grimshot: str
    swappy: str
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


def capture_screenshot_to_file(settings: CaptureSettings) -> Path:
    settings.target_dir.mkdir(parents=True, exist_ok=True)

    if settings.use_swappy:
        raw_path = capture_raw_screenshot(grimshot=settings.grimshot, mode=settings.mode)
        try:
            return edit_raw_capture(
                raw_path,
                target_dir=settings.target_dir,
                filename_template=settings.filename_template,
                swappy=settings.swappy,
            )
        finally:
            raw_path.unlink(missing_ok=True)

    output_path = render_output_path(settings.target_dir, settings.filename_template)
    try:
        run_checked([settings.grimshot, "save", settings.mode, str(output_path)], env=capture_env())
    except RuntimeError:
        output_path.unlink(missing_ok=True)
        raise
    reject_empty_capture(output_path)
    return output_path


def capture_screenshot_to_clipboard(settings: CaptureSettings) -> None:
    raw_path = capture_raw_screenshot(grimshot=settings.grimshot, mode=settings.mode)
    try:
        start_wl_copy(settings.wl_copy, raw_path.read_bytes())
    finally:
        raw_path.unlink(missing_ok=True)


def start_wl_copy(wl_copy: str, payload: bytes) -> None:
    proc = subprocess.Popen(
        [wl_copy, "--type", "image/png"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if proc.stdin is None:
        raise RuntimeError("wl-copy stdin pipe was not created")
    proc.stdin.write(payload)
    proc.stdin.close()
    try:
        rc = proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        # wl-copy may remain in the foreground as the clipboard owner on some setups.
        # That is a successful clipboard hand-off for our purposes; do not block flosh.
        return
    stderr = proc.stderr.read() if proc.stderr is not None else b""
    if rc != 0:
        details = (stderr or b"").decode(errors="replace").strip()
        raise RuntimeError(details or f"wl-copy failed with exit code {rc}")


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
    swappy: str,
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = render_output_path(target_dir, filename_template)
    try:
        run_checked([swappy, "-f", str(raw_path), "-o", str(output_path)], env=capture_env())
        reject_empty_capture(output_path)
        reject_unchanged_swappy_output(raw_path, output_path)
    except RuntimeError:
        output_path.unlink(missing_ok=True)
        raise
    return output_path


def reject_unchanged_swappy_output(raw_path: Path, output_path: Path) -> None:
    try:
        unchanged = filecmp.cmp(raw_path, output_path, shallow=False)
    except OSError:
        unchanged = False
    if unchanged:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("swappy output is unchanged; treating it as cancelled")


def capture_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("WLR_NO_HARDWARE_CURSORS", "1")
    return env


def run_checked(cmd: list[str], *, env: dict[str, str]) -> None:
    proc = subprocess.run(cmd, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed with exit code {proc.returncode}: {' '.join(cmd[:3])}")


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
