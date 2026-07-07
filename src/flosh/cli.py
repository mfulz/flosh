from __future__ import annotations

from pathlib import Path

import typer

from flosh.config import (
    ConfigFormat,
    RuntimeContext,
    config_get,
    edit_config,
    init_config,
    make_runtime_context,
    render_config,
    resolve_config,
)
from flosh.config import (
    config_set as write_config_value,
)

app = typer.Typer(
    name="flosh",
    help="Wayland-first capture, OCR, clipboard typing, and target-directory workflows.",
    no_args_is_help=True,
)

config_app = typer.Typer(help="Inspect and manage flosh configuration files.")
target_app = typer.Typer(help="Inspect and manage the active capture target directory.")
take_app = typer.Typer(help="Capture screenshots and route them through save/edit flows.")
paste_app = typer.Typer(help="Type clipboard or text into the focused application.")
ocr_app = typer.Typer(help="Capture and OCR screen content.")

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
def target_show() -> None:
    """Print the active capture target directory."""
    typer.echo("not implemented yet")


@target_app.command("set")
def target_set(path: str) -> None:
    """Set the active capture target directory."""
    typer.echo(f"not implemented yet: {path}")


@target_app.command("pick")
def target_pick() -> None:
    """Interactively choose the active capture target directory."""
    typer.echo("not implemented yet")


@take_app.callback(invoke_without_command=True)
def take_default() -> None:
    """Take a screenshot using configured defaults."""
    typer.echo("not implemented yet")


@paste_app.command("clipboard")
def paste_clipboard() -> None:
    """Type the current clipboard into the focused application."""
    typer.echo("not implemented yet")


@ocr_app.command("capture")
def ocr_capture() -> None:
    """Capture an area and run OCR."""
    typer.echo("not implemented yet")
