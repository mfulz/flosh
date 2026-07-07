from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SELECT_HERE = "✔ Select this directory"
GO_UP = "../"
CREATE_HERE = "+ Create new folder here"


def choose_picker(requested: str) -> str:
    if requested != "auto":
        return requested
    if shutil.which("wofi") and os.environ.get("WAYLAND_DISPLAY"):
        return "wofi"
    if shutil.which("rofi"):
        return "rofi"
    if shutil.which("fzf") and sys.stdin.isatty():
        return "fzf"
    return "stdin"


def pick_from_menu(entries: list[str], *, prompt: str, picker: str) -> str | None:
    if not entries:
        return None

    menu_input = "\n".join(entries) + "\n"
    selected = choose_picker(picker)

    if selected == "wofi":
        proc = subprocess.run(
            [shutil.which("wofi") or "wofi", "--dmenu", "--prompt", prompt],
            input=menu_input,
            text=True,
            capture_output=True,
            check=False,
        )
        return (proc.stdout or "").strip() or None

    if selected == "rofi":
        proc = subprocess.run(
            [shutil.which("rofi") or "rofi", "-dmenu", "-p", prompt],
            input=menu_input,
            text=True,
            capture_output=True,
            check=False,
        )
        return (proc.stdout or "").strip() or None

    if selected == "fzf":
        proc = subprocess.run(
            [shutil.which("fzf") or "fzf", f"--prompt={prompt}> "],
            input=menu_input,
            text=True,
            capture_output=True,
            check=False,
        )
        return (proc.stdout or "").strip() or None

    print("Available entries:", file=sys.stderr)
    for entry in entries:
        print(f"- {entry}", file=sys.stderr)
    try:
        return input(f"{prompt}: ").strip() or None
    except EOFError:
        return None


def prompt_text(*, prompt: str, picker: str) -> str | None:
    selected = choose_picker(picker)
    if selected == "wofi":
        proc = subprocess.run(
            [shutil.which("wofi") or "wofi", "--dmenu", "--prompt", prompt],
            input="",
            text=True,
            capture_output=True,
            check=False,
        )
        return (proc.stdout or "").strip() or None
    if selected == "rofi":
        proc = subprocess.run(
            [shutil.which("rofi") or "rofi", "-dmenu", "-p", prompt],
            input="",
            text=True,
            capture_output=True,
            check=False,
        )
        return (proc.stdout or "").strip() or None
    try:
        return input(f"{prompt}: ").strip() or None
    except EOFError:
        return None


def normalize(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def within_root(root: Path, candidate: Path) -> bool:
    try:
        normalize(candidate).relative_to(normalize(root))
        return True
    except ValueError:
        return False


def list_child_directories(base: Path, *, include_hidden: bool) -> list[Path]:
    children: list[Path] = []
    try:
        with os.scandir(base) as entries:
            for entry in entries:
                if not include_hidden and entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=True):
                        children.append(Path(entry.path).resolve(strict=False))
                except OSError:
                    continue
    except OSError:
        return []
    children.sort(key=lambda item: item.name.lower())
    return children


def create_under(root: Path, current: Path, *, picker: str) -> Path | None:
    rel = prompt_text(prompt=f"New folder under {current.name or current}", picker=picker)
    if not rel:
        return None
    candidate = normalize(current / rel)
    if not within_root(root, candidate):
        raise ValueError(f"refusing to create outside root: {candidate}")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def browse_directory(
    root: Path,
    *,
    start: Path | None = None,
    include_hidden: bool = False,
    allow_create: bool = False,
    picker: str = "auto",
) -> Path | None:
    root = normalize(root)
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    current = normalize(start) if start else root
    if not within_root(root, current):
        current = root
    if not current.exists() or not current.is_dir():
        current = root

    while True:
        entries = [SELECT_HERE]
        if current != root:
            entries.append(GO_UP)
        entries.extend(
            f"{child.name}/"
            for child in list_child_directories(current, include_hidden=include_hidden)
        )
        if allow_create:
            entries.append(CREATE_HERE)

        rel = "." if current == root else str(current.relative_to(root))
        choice = pick_from_menu(entries, prompt=f"flosh target [{rel}]", picker=picker)
        if not choice:
            return None
        if choice == SELECT_HERE:
            return current
        if choice == GO_UP:
            current = current.parent
            continue
        if choice == CREATE_HERE:
            created = create_under(root, current, picker=picker)
            if created is not None:
                return created
            continue
        if choice.endswith("/"):
            current = current / choice[:-1]
            continue
        raise ValueError(f"unexpected picker choice: {choice}")
