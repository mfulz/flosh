from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
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


def pick_from_menu(
    entries: list[str],
    *,
    prompt: str,
    picker: str,
    terminal: str | None = None,
) -> str | None:
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
        return run_fzf(menu_input, prompt=prompt, terminal=terminal)

    print("Available entries:", file=sys.stderr)
    for entry in entries:
        print(f"- {entry}", file=sys.stderr)
    try:
        return input(f"{prompt}: ").strip() or None
    except EOFError:
        return None


def prompt_text(*, prompt: str, picker: str, terminal: str | None = None) -> str | None:
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
    if selected == "fzf" and not sys.stdin.isatty():
        return prompt_text_in_terminal(prompt=prompt, terminal=terminal)
    try:
        return input(f"{prompt}: ").strip() or None
    except EOFError:
        return None


def run_fzf(menu_input: str, *, prompt: str, terminal: str | None) -> str | None:
    if sys.stdin.isatty():
        proc = subprocess.run(
            [shutil.which("fzf") or "fzf", "--print-query", f"--prompt={prompt}> "],
            input=menu_input,
            text=True,
            capture_output=True,
            check=False,
        )
        return parse_fzf_output(proc.stdout)
    return run_fzf_in_terminal(menu_input, prompt=prompt, terminal=terminal)


def parse_fzf_output(output: str) -> str | None:
    lines = output.splitlines()
    if not lines:
        return None
    if len(lines) >= 2 and lines[-1].strip():
        return lines[-1].strip()
    return lines[0].strip() or None


def run_fzf_in_terminal(menu_input: str, *, prompt: str, terminal: str | None) -> str | None:
    terminal_cmd = shlex.split(terminal or os.environ.get("TERMINAL") or "alacritty")
    with tempfile.NamedTemporaryFile(
        "w",
        prefix="flosh-fzf-entries-",
        delete=False,
    ) as entries_file:
        entries_file.write(menu_input)
        entries_path = Path(entries_file.name)
    with tempfile.NamedTemporaryFile("w", prefix="flosh-fzf-output-", delete=False) as output_file:
        output_path = Path(output_file.name)
    try:
        script = 'fzf --print-query --prompt "$1> " < "$2" > "$3"'
        proc = subprocess.run(
            [
                *terminal_cmd,
                "-e",
                "sh",
                "-c",
                script,
                "flosh-fzf",
                prompt,
                str(entries_path),
                str(output_path),
            ],
            check=False,
        )
        if proc.returncode != 0:
            return None
        return parse_fzf_output(output_path.read_text(encoding="utf-8"))
    finally:
        entries_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


def prompt_text_in_terminal(*, prompt: str, terminal: str | None) -> str | None:
    terminal_cmd = shlex.split(terminal or os.environ.get("TERMINAL") or "alacritty")
    with tempfile.NamedTemporaryFile(
        "w",
        prefix="flosh-prompt-output-",
        delete=False,
    ) as output_file:
        output_path = Path(output_file.name)
    try:
        script = 'printf "%s: " "$1"; IFS= read -r value; printf "%s" "$value" > "$2"'
        proc = subprocess.run(
            [
                *terminal_cmd,
                "-e",
                "sh",
                "-c",
                script,
                "flosh-prompt",
                prompt,
                str(output_path),
            ],
            check=False,
        )
        if proc.returncode != 0:
            return None
        return output_path.read_text(encoding="utf-8").strip() or None
    finally:
        output_path.unlink(missing_ok=True)


def normalize(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def within_root(root: Path, candidate: Path) -> bool:
    try:
        normalize(candidate).relative_to(normalize(root))
        return True
    except ValueError:
        return False


def nearest_existing_directory(path: Path, *, fallback: Path) -> Path:
    current = normalize(path)
    root = normalize(fallback)
    while within_root(root, current):
        if current.exists() and current.is_dir():
            return current
        if current == current.parent:
            break
        current = current.parent
    return root


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


def create_under(
    root: Path,
    current: Path,
    *,
    picker: str,
    terminal: str | None = None,
) -> Path | None:
    rel = prompt_text(
        prompt=f"New folder under {current.name or current}",
        picker=picker,
        terminal=terminal,
    )
    if not rel:
        return None
    candidate = normalize(Path(rel) if Path(rel).expanduser().is_absolute() else current / rel)
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
    terminal: str | None = None,
) -> Path | None:
    root = normalize(root)
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    current = normalize(start) if start else root
    if not within_root(root, current):
        current = root
    current = nearest_existing_directory(current, fallback=root)

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
        choice = pick_from_menu(
            entries,
            prompt=f"flosh target [{rel}]",
            picker=picker,
            terminal=terminal,
        )
        if not choice:
            return None
        if choice == SELECT_HERE:
            return current
        if choice == GO_UP:
            current = current.parent
            continue
        if choice == CREATE_HERE:
            created = create_under(root, current, picker=picker, terminal=terminal)
            if created is not None:
                return created
            continue
        if choice.endswith("/"):
            current = current / choice[:-1]
            continue
        typed = resolve_typed_path(choice, current=current)
        if typed is not None:
            if not within_root(root, typed):
                raise ValueError(f"path is outside picker root: {typed}")
            if typed.exists() and typed.is_dir():
                return typed
            if typed.exists():
                raise ValueError(f"path exists but is not a directory: {typed}")
            if allow_create:
                typed.mkdir(parents=True, exist_ok=True)
                return typed
            raise ValueError(f"directory does not exist: {typed}; use --create")
        raise ValueError(f"unexpected picker choice: {choice}")


def resolve_typed_path(choice: str, *, current: Path) -> Path | None:
    raw = choice.strip()
    if not raw:
        return None
    if raw.startswith("~") or Path(raw).is_absolute():
        return normalize(Path(raw))
    if "/" in raw:
        return normalize(current / raw)
    return None
