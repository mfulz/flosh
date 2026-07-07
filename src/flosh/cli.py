from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from flosh import picker as picker_mod
from flosh.config import (
    ConfigFormat,
    RuntimeContext,
    config_get,
    edit_config,
    get_dotted,
    init_config,
    make_runtime_context,
    render_config,
    resolve_config,
)
from flosh.config import (
    config_set as write_config_value,
)
from flosh.paste import Backend, PasteSettings, read_clipboard, type_text
from flosh.state import effective_target, recent_limit, state_path, target_root, update_target

app = typer.Typer(
    name="flosh",
    help="Wayland-first capture, OCR, clipboard typing, and target-directory workflows.",
    no_args_is_help=True,
)

config_app = typer.Typer(
    help="Inspect and manage flosh configuration files.",
    no_args_is_help=True,
)
target_app = typer.Typer(
    help="Inspect and manage the active capture target directory.",
    no_args_is_help=True,
)
take_app = typer.Typer(
    help="Capture screenshots and route them through save/edit flows.",
    no_args_is_help=True,
)
paste_app = typer.Typer(
    help="Type clipboard or text into the focused application.",
    no_args_is_help=True,
)
ocr_app = typer.Typer(help="Capture and OCR screen content.", no_args_is_help=True)

app.add_typer(config_app, name="config")
app.add_typer(target_app, name="target")
app.add_typer(take_app, name="take")
app.add_typer(paste_app, name="paste")
app.add_typer(ocr_app, name="ocr")


def ctx_obj(ctx: typer.Context) -> RuntimeContext:
    obj = ctx.obj
    if not isinstance(obj, RuntimeContext):
        raise RuntimeError("flosh runtime context missing")
    return obj


@app.callback()
def main(
    ctx: typer.Context,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        envvar="FLOSH_CONFIG",
        help="Configuration file to load. Defaults to the user config path.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        envvar="FLOSH_PROFILE",
        help="Optional named profile inside the configuration file.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        envvar="FLOSH_VERBOSE",
        help="Enable verbose diagnostic output.",
    ),
) -> None:
    """Run flosh.

    Setting precedence is: CLI arguments > environment variables > config file > defaults.
    """
    ctx.obj = make_runtime_context(config=config, profile=profile, verbose=verbose)


@config_app.command("path")
def config_path(ctx: typer.Context) -> None:
    """Print the effective configuration path."""
    typer.echo(ctx_obj(ctx).config_path)


@config_app.command("show")
def config_show(
    ctx: typer.Context,
    output_format: ConfigFormat = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format.",
    ),
    sources: bool = typer.Option(
        False,
        "--sources",
        help="Show value sources instead of normal config rendering.",
    ),
) -> None:
    """Print the merged effective configuration."""
    resolved = resolve_config(ctx_obj(ctx))
    typer.echo(render_config(resolved, output_format, include_sources=sources))


@config_app.command("init")
def config_init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config file."),
) -> None:
    """Create a starter configuration file."""
    path = ctx_obj(ctx).config_path
    try:
        init_config(path, force=force)
    except FileExistsError:
        raise typer.BadParameter(f"config already exists: {path}; use --force") from None
    typer.echo(path)


@config_app.command("get")
def config_get_cmd(ctx: typer.Context, key: str = typer.Argument(...)) -> None:
    """Print a merged effective config value by dotted key."""
    try:
        value = config_get(ctx_obj(ctx), key)
    except KeyError:
        raise typer.BadParameter(f"unknown config key: {key}") from None
    typer.echo(value)


@config_app.command("set")
def config_set_cmd(
    ctx: typer.Context,
    key: str = typer.Argument(...),
    value: str = typer.Argument(...),
) -> None:
    """Set a value in the selected config file by dotted key."""
    path = ctx_obj(ctx).config_path
    write_config_value(path, key, value)
    typer.echo(f"{key} = {value}")


@config_app.command("edit")
def config_edit(ctx: typer.Context) -> None:
    """Open the selected config file in $EDITOR."""
    edit_config(ctx_obj(ctx).config_path)


@target_app.command("show")
def target_show(
    ctx: typer.Context,
    short: bool = typer.Option(False, "--short", help="Print only the directory basename."),
    json_output: bool = typer.Option(False, "--json", help="Print Waybar-compatible JSON."),
) -> None:
    """Print the active capture target directory."""
    resolved = resolve_config(ctx_obj(ctx))
    target = effective_target(resolved).expanduser()

    if json_output:
        payload = {
            "text": target.name or str(target),
            "tooltip": str(target),
            "class": "flosh-target",
        }
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    typer.echo(target.name if short else target)


@target_app.command("set")
def target_set(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Target directory to store in flosh state."),
    create: bool = typer.Option(
        False,
        "--create",
        help="Create the directory if it does not exist.",
    ),
    print_only: bool = typer.Option(
        False,
        "--print-only",
        help="Print resolved path without writing state.",
    ),
) -> None:
    """Set the active capture target directory."""
    resolved = resolve_config(ctx_obj(ctx))
    target = path.expanduser().resolve(strict=False)
    if target.exists() and not target.is_dir():
        raise typer.BadParameter(f"target exists but is not a directory: {target}")
    if not target.exists():
        if create:
            target.mkdir(parents=True, exist_ok=True)
        else:
            raise typer.BadParameter(f"target does not exist: {target}; use --create")

    if not print_only:
        update_target(state_path(resolved), target, recent_limit=recent_limit(resolved))
    typer.echo(target)


@target_app.command("pick")
def target_pick(
    ctx: typer.Context,
    root: Path | None = typer.Option(
        None,
        "--root",
        envvar="FLOSH_TARGET_ROOT",
        help="Root directory used as picker boundary.",
    ),
    start_current: bool = typer.Option(
        False,
        "--start-current",
        help="Start browsing at the current target if it is below root.",
    ),
    create: bool = typer.Option(False, "--create", help="Allow creating directories."),
    include_hidden: bool = typer.Option(False, "--include-hidden", help="Show hidden directories."),
    picker: str | None = typer.Option(
        None,
        "--picker",
        envvar="FLOSH_PICKER",
        help="Picker backend: auto, fzf, wofi, rofi, stdin.",
    ),
    print_only: bool = typer.Option(
        False,
        "--print-only",
        help="Print selection without writing state.",
    ),
) -> None:
    """Interactively choose the active capture target directory."""
    resolved = resolve_config(ctx_obj(ctx))
    selected_root = (root.expanduser() if root else target_root(resolved)).resolve(strict=False)
    selected_picker = picker or str(get_dotted(resolved.data, "capture.picker"))
    start = effective_target(resolved) if start_current else None

    try:
        selected = picker_mod.browse_directory(
            selected_root,
            start=start,
            include_hidden=include_hidden,
            allow_create=create,
            picker=selected_picker,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None

    if selected is None:
        raise typer.Exit(1)

    if not print_only:
        update_target(state_path(resolved), selected, recent_limit=recent_limit(resolved))
    typer.echo(selected)


@take_app.callback(invoke_without_command=True)
def take_default() -> None:
    """Take a screenshot using configured defaults."""
    typer.echo("not implemented yet")


def paste_settings(
    ctx: typer.Context,
    *,
    backend: Backend | None,
    wait_s: float | None,
    delay_ms: int | None,
) -> PasteSettings:
    resolved = resolve_config(ctx_obj(ctx))
    selected_backend = backend or str(get_dotted(resolved.data, "paste.backend"))
    if selected_backend not in {"xdotool", "wtype", "ydotool"}:
        raise typer.BadParameter(f"unsupported paste backend: {selected_backend}")
    return PasteSettings(
        backend=selected_backend,  # type: ignore[arg-type]
        wait_s=wait_s if wait_s is not None else float(get_dotted(resolved.data, "paste.wait_s")),
        delay_ms=delay_ms
        if delay_ms is not None
        else int(get_dotted(resolved.data, "paste.delay_ms")),
        wl_paste=str(get_dotted(resolved.data, "tools.wl_paste")),
        xdotool=str(get_dotted(resolved.data, "tools.xdotool")),
        wtype=str(get_dotted(resolved.data, "tools.wtype")),
        ydotool=str(get_dotted(resolved.data, "tools.ydotool")),
    )


def run_paste(text: str, settings: PasteSettings) -> None:
    try:
        type_text(text, settings)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from None


@paste_app.command("clipboard")
def paste_clipboard(
    ctx: typer.Context,
    backend: Backend | None = typer.Option(
        None,
        "--backend",
        envvar="FLOSH_PASTE_BACKEND",
        help="Typing backend: xdotool, wtype, ydotool.",
    ),
    wait_s: float | None = typer.Option(
        None,
        "--wait-s",
        envvar="FLOSH_PASTE_WAIT_S",
        help="Seconds to wait before typing.",
    ),
    delay_ms: int | None = typer.Option(
        None,
        "--delay-ms",
        envvar="FLOSH_PASTE_DELAY_MS",
        help="Delay between typed characters in milliseconds.",
    ),
) -> None:
    """Type the current clipboard into the focused application."""
    settings = paste_settings(ctx, backend=backend, wait_s=wait_s, delay_ms=delay_ms)
    try:
        text = read_clipboard(wl_paste=settings.wl_paste)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from None
    run_paste(text, settings)


@paste_app.command("text")
def paste_text(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Literal text to type."),
    backend: Backend | None = typer.Option(
        None,
        "--backend",
        envvar="FLOSH_PASTE_BACKEND",
        help="Typing backend: xdotool, wtype, ydotool.",
    ),
    wait_s: float | None = typer.Option(
        None,
        "--wait-s",
        envvar="FLOSH_PASTE_WAIT_S",
        help="Seconds to wait before typing.",
    ),
    delay_ms: int | None = typer.Option(
        None,
        "--delay-ms",
        envvar="FLOSH_PASTE_DELAY_MS",
        help="Delay between typed characters in milliseconds.",
    ),
) -> None:
    """Type literal text into the focused application."""
    settings = paste_settings(ctx, backend=backend, wait_s=wait_s, delay_ms=delay_ms)
    run_paste(text, settings)


@paste_app.command("stdin")
def paste_stdin(
    ctx: typer.Context,
    backend: Backend | None = typer.Option(
        None,
        "--backend",
        envvar="FLOSH_PASTE_BACKEND",
        help="Typing backend: xdotool, wtype, ydotool.",
    ),
    wait_s: float | None = typer.Option(
        None,
        "--wait-s",
        envvar="FLOSH_PASTE_WAIT_S",
        help="Seconds to wait before typing.",
    ),
    delay_ms: int | None = typer.Option(
        None,
        "--delay-ms",
        envvar="FLOSH_PASTE_DELAY_MS",
        help="Delay between typed characters in milliseconds.",
    ),
) -> None:
    """Read stdin and type it into the focused application."""
    settings = paste_settings(ctx, backend=backend, wait_s=wait_s, delay_ms=delay_ms)
    run_paste(sys.stdin.read(), settings)


@ocr_app.command("capture")
def ocr_capture() -> None:
    """Capture an area and run OCR."""
    typer.echo("not implemented yet")
