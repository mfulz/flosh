from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

import typer

from flosh import picker as picker_mod
from flosh.capture import (
    MENU_CANCEL,
    MENU_EDITOR,
    MENU_SAVE,
    MENU_SELECT_DIR,
    CaptureCancelled,
    CaptureCommandSettings,
    CaptureDestination,
    CaptureMode,
    CaptureSettings,
    capture_raw_screenshot,
    capture_screenshot_to_clipboard,
    capture_screenshot_to_file,
    command_for_mode,
    destination_for_profile,
    notify,
    open_raw_in_editor,
    run_capture_command,
    save_raw_capture,
)
from flosh.config import (
    ConfigFormat,
    ResolvedConfig,
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
from flosh.ocr import OcrSettings, capture_ocr_text, copy_text_to_clipboard, save_ocr_text
from flosh.paste import Backend, Keymap, PasteSettings, read_clipboard, type_text
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


TargetTextMode = Literal["basename", "path", "compact"]


def compact_path(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def format_target_text(target: Path, *, mode: TargetTextMode, max_length: int) -> str:
    expanded = target.expanduser()
    if mode == "basename":
        text = expanded.name or str(expanded)
    elif mode == "path":
        text = str(expanded)
    elif mode == "compact":
        text = compact_path(expanded)
    else:
        raise ValueError(f"unsupported text mode: {mode}")

    if max_length > 0 and len(text) > max_length:
        return "…" + text[-(max_length - 1) :] if max_length > 1 else "…"
    return text


def target_json_payload(
    resolved: ResolvedConfig,
    target: Path,
    *,
    mode: TargetTextMode,
    max_length: int,
) -> dict[str, object]:
    path = target.expanduser()
    classes = ["flosh-target"]
    classes.append("exists" if path.exists() else "missing")
    return {
        "text": format_target_text(path, mode=mode, max_length=max_length),
        "tooltip": target_tooltip(resolved, path),
        "class": classes,
        "alt": str(path),
    }


def target_tooltip(resolved: ResolvedConfig, target: Path) -> str:
    profile = resolved.profile or "default"
    lines = [
        "flosh",
        f"target: {target}",
        f"config: {resolved.path}",
        f"profile: {profile}",
        f"state: {state_path(resolved)}",
        "",
        "capture",
        f"  mode: {get_dotted(resolved.data, 'capture.default_mode')}",
        f"  profile: {get_dotted(resolved.data, 'capture.default_profile')}",
        f"  destination: {get_dotted(resolved.data, 'capture.default_destination')}",
        f"  filename: {get_dotted(resolved.data, 'capture.filename_template')}",
        f"  picker: {get_dotted(resolved.data, 'capture.picker')}",
        "",
        "target picker",
        f"  root: {Path(str(get_dotted(resolved.data, 'target.root'))).expanduser()}",
        f"  start: {get_dotted(resolved.data, 'target.start')}",
        f"  create: {get_dotted(resolved.data, 'target.create')}",
        "",
        "ocr",
        f"  lang: {get_dotted(resolved.data, 'ocr.lang')}",
        f"  psm: {get_dotted(resolved.data, 'ocr.psm')}",
        f"  preprocess: {get_dotted(resolved.data, 'ocr.preprocess')}",
        "",
        "paste",
        f"  backend: {get_dotted(resolved.data, 'paste.backend')}",
        f"  keymap: {get_dotted(resolved.data, 'paste.keymap')}",
        f"  wait_s: {get_dotted(resolved.data, 'paste.wait_s')}",
        f"  delay_ms: {get_dotted(resolved.data, 'paste.delay_ms')}",
    ]
    return "\n".join(lines)


@target_app.command("show")
def target_show(
    ctx: typer.Context,
    short: bool = typer.Option(False, "--short", help="Print only the directory basename."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    text_mode: TargetTextMode = typer.Option(
        "compact",
        "--text-mode",
        help="JSON text field: basename, compact, or path.",
    ),
    max_length: int = typer.Option(
        80,
        "--max-length",
        help="Ellipsize JSON text from the left. Use 0 to disable.",
    ),
) -> None:
    """Print the active capture target directory."""
    resolved = resolve_config(ctx_obj(ctx))
    target = effective_target(resolved).expanduser()

    if json_output:
        payload = target_json_payload(resolved, target, mode=text_mode, max_length=max_length)
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    typer.echo(target.name if short else target)


@target_app.command("set")
def target_set(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Target directory to store in flosh state."),
    create: bool | None = typer.Option(
        None,
        "--create/--no-create",
        help="Create the directory if missing. Defaults to target.create.",
    ),
    print_only: bool = typer.Option(
        False,
        "--print-only",
        help="Print resolved path without writing state.",
    ),
) -> None:
    """Set the active capture target directory."""
    resolved = resolve_config(ctx_obj(ctx))
    create_missing = create
    if create_missing is None:
        create_missing = bool(get_dotted(resolved.data, "target.create"))

    target = path.expanduser().resolve(strict=False)
    if target.exists() and not target.is_dir():
        raise typer.BadParameter(f"target exists but is not a directory: {target}")
    if not target.exists():
        if create_missing:
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
        help="Optional picker boundary. Defaults to / and starts at target.root.",
    ),
    start_current: bool | None = typer.Option(
        None,
        "--start-current/--no-start-current",
        help="Start browsing at current target. Defaults to target.start.",
    ),
    create: bool | None = typer.Option(
        None,
        "--create/--no-create",
        help="Allow creating directories. Defaults to target.create.",
    ),
    include_hidden: bool = typer.Option(False, "--include-hidden", help="Show hidden directories."),
    picker: str | None = typer.Option(
        None,
        "--picker",
        envvar="FLOSH_PICKER",
        help="Picker backend: auto, fzf, wofi, rofi, stdin.",
    ),
    terminal: str | None = typer.Option(
        None,
        "--terminal",
        envvar="FLOSH_TERMINAL",
        help="Terminal command used when fzf needs a GUI terminal.",
    ),
    print_only: bool = typer.Option(
        False,
        "--print-only",
        help="Print selection without writing state.",
    ),
) -> None:
    """Interactively choose the active capture target directory."""
    resolved = resolve_config(ctx_obj(ctx))
    selected = pick_target_interactive(
        resolved,
        root=root,
        start_current=start_current,
        create=create,
        include_hidden=include_hidden,
        picker=picker,
        terminal=terminal,
        write_state=not print_only,
    )
    if selected is None:
        raise typer.Exit(1)
    typer.echo(selected)


def pick_target_interactive(
    resolved: ResolvedConfig,
    *,
    root: Path | None,
    start_current: bool | None,
    create: bool | None,
    include_hidden: bool,
    picker: str | None,
    terminal: str | None,
    write_state: bool,
) -> Path | None:
    selected_root, start = default_pick_root_and_start(
        resolved,
        explicit_root=root,
        start_current=start_current,
    )
    selected_picker = picker or str(get_dotted(resolved.data, "capture.picker"))
    selected_terminal = terminal or str(get_dotted(resolved.data, "tools.terminal"))
    selected_terminal_class = str(get_dotted(resolved.data, "tools.terminal_class"))
    create_missing = create
    if create_missing is None:
        create_missing = bool(get_dotted(resolved.data, "target.create"))

    try:
        selected = picker_mod.browse_directory(
            selected_root,
            start=start,
            include_hidden=include_hidden,
            allow_create=create_missing,
            picker=selected_picker,
            terminal=selected_terminal,
            terminal_class=selected_terminal_class,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None

    if selected is not None and write_state:
        update_target(state_path(resolved), selected, recent_limit=recent_limit(resolved))
    return selected


def capture_settings(
    ctx: typer.Context,
    *,
    mode: CaptureMode | None,
    filename_template: str | None,
    no_swappy: bool,
) -> CaptureSettings:
    resolved = resolve_config(ctx_obj(ctx))
    selected_mode = mode or str(get_dotted(resolved.data, "capture.default_mode"))
    if selected_mode not in {"area", "screen", "output", "active", "window"}:
        raise typer.BadParameter(f"unsupported capture mode: {selected_mode}")
    selected_editor = str(get_dotted(resolved.data, "capture.editor"))
    if selected_editor not in {"satty", "swappy"}:
        raise typer.BadParameter(f"unsupported capture.editor: {selected_editor}")
    return CaptureSettings(
        target_dir=effective_target(resolved).expanduser(),
        mode=selected_mode,  # type: ignore[arg-type]
        filename_template=filename_template
        if filename_template is not None
        else str(get_dotted(resolved.data, "capture.filename_template")),
        use_swappy=not no_swappy,
        editor=selected_editor,  # type: ignore[arg-type]
        grimshot=str(get_dotted(resolved.data, "tools.grimshot")),
        swappy=str(get_dotted(resolved.data, "tools.swappy")),
        satty=str(get_dotted(resolved.data, "tools.satty")),
        wl_copy=str(get_dotted(resolved.data, "tools.wl_copy")),
        picker=str(get_dotted(resolved.data, "capture.picker")),
    )


def print_capture_result(path: Path, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps({"path": str(path), "name": path.name}, sort_keys=True))


def print_clipboard_result(*, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps({"destination": "clipboard"}, sort_keys=True))



def capture_command_settings(
    ctx: typer.Context,
    *,
    mode: CaptureMode | None,
    filename_template: str | None,
    capture_profile: str | None,
    save: bool,
    clipboard: bool,
) -> CaptureCommandSettings:
    resolved = resolve_config(ctx_obj(ctx))
    selected_mode = mode or str(get_dotted(resolved.data, "capture.default_mode"))
    if selected_mode not in {"area", "screen", "output", "active", "window"}:
        raise typer.BadParameter(f"unsupported capture mode: {selected_mode}")

    profile_name = capture_profile or str(get_dotted(resolved.data, "capture.default_profile"))
    profiles = get_dotted(resolved.data, "capture.profiles")
    if not isinstance(profiles, dict):
        raise typer.BadParameter("capture.profiles must be a table")
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise typer.BadParameter(f"unknown capture profile: {profile_name}")

    try:
        command = command_for_mode(profile, selected_mode)  # type: ignore[arg-type]
        destination = destination_for_profile(
            profile,
            configured_default=str(get_dotted(resolved.data, "capture.default_destination")),
            save=save,
            clipboard=clipboard,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    tools = get_dotted(resolved.data, "tools")
    tool_variables = (
        {str(key): str(value) for key, value in tools.items() if not isinstance(value, dict)}
        if isinstance(tools, dict)
        else {}
    )
    return CaptureCommandSettings(
        target_dir=effective_target(resolved).expanduser(),
        mode=selected_mode,  # type: ignore[arg-type]
        filename_template=filename_template
        if filename_template is not None
        else str(get_dotted(resolved.data, "capture.filename_template")),
        profile_name=profile_name,
        command=command,
        destination=destination,
        variables=tool_variables,
    )


def capture_destination(
    ctx: typer.Context,
    *,
    save: bool,
    clipboard: bool,
) -> CaptureDestination:
    if save and clipboard:
        raise typer.BadParameter("--save and --clipboard are mutually exclusive")
    if save:
        return "file"
    if clipboard:
        return "clipboard"
    resolved = resolve_config(ctx_obj(ctx))
    configured = str(get_dotted(resolved.data, "capture.default_destination"))
    if configured not in {"clipboard", "file"}:
        raise typer.BadParameter(f"unsupported capture.default_destination: {configured}")
    return configured  # type: ignore[return-value]


def default_pick_root_and_start(
    resolved_config: ResolvedConfig,
    *,
    explicit_root: Path | None,
    start_current: bool | None,
) -> tuple[Path, Path | None]:
    should_start_current = resolve_start_current(resolved_config, start_current)
    if explicit_root is not None:
        root = explicit_root.expanduser().resolve(strict=False)
        start = effective_target(resolved_config).expanduser() if should_start_current else None
        return root, start
    root = Path("/")
    start = (
        effective_target(resolved_config).expanduser()
        if should_start_current
        else target_root(resolved_config).expanduser()
    )
    return root, start


def resolve_start_current(
    resolved_config: ResolvedConfig,
    start_current: bool | None,
) -> bool:
    if start_current is not None:
        return start_current
    configured = str(get_dotted(resolved_config.data, "target.start")).strip().lower()
    if configured in {"current", "target", "state"}:
        return True
    if configured in {"root", "default"}:
        return False
    raise typer.BadParameter(f"unsupported target.start: {configured}")


@take_app.callback(invoke_without_command=True)
def take_default(
    ctx: typer.Context,
    mode: CaptureMode | None = typer.Option(
        None,
        "--mode",
        envvar="FLOSH_CAPTURE_MODE",
        help="Capture mode: area, screen, output, active, window.",
    ),
    filename_template: str | None = typer.Option(
        None,
        "--filename-template",
        envvar="FLOSH_FILENAME_TEMPLATE",
        help="strftime filename template for saved screenshots.",
    ),
    capture_profile: str | None = typer.Option(
        None,
        "--capture-profile",
        envvar="FLOSH_CAPTURE_PROFILE",
        help="Capture command profile from capture.profiles.",
    ),
    no_swappy: bool = typer.Option(
        False,
        "--no-swappy",
        help="Legacy: bypass capture profiles and use flosh direct output.",
    ),
    save: bool = typer.Option(
        False,
        "--save",
        help="Force file destination semantics for the selected capture flow.",
    ),
    clipboard: bool = typer.Option(
        False,
        "--clipboard",
        help="Force clipboard destination semantics for the selected capture flow.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Take a screenshot using configured defaults."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        if not no_swappy:
            command_settings = capture_command_settings(
                ctx,
                mode=mode,
                filename_template=filename_template,
                capture_profile=capture_profile,
                save=save,
                clipboard=clipboard,
            )
            output = run_capture_command(command_settings)
            if output is None:
                notify("Screenshot copied", command_settings.profile_name)
                print_clipboard_result(json_output=json_output)
                return
            notify("Screenshot saved", output.name)
            print_capture_result(output, json_output=json_output)
            return

        settings = capture_settings(
            ctx,
            mode=mode,
            filename_template=filename_template,
            no_swappy=no_swappy,
        )
        destination = capture_destination(ctx, save=save, clipboard=clipboard)
        if destination == "clipboard":
            capture_screenshot_to_clipboard(settings)
            notify("Screenshot copied", "image/png")
            print_clipboard_result(json_output=json_output)
            return
        output = capture_screenshot_to_file(settings)
    except CaptureCancelled:
        notify("Screenshot cancelled")
        raise typer.Exit(1) from None
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None
    notify("Screenshot saved", output.name)
    print_capture_result(output, json_output=json_output)


@take_app.command("menu")
def take_menu(
    ctx: typer.Context,
    mode: CaptureMode | None = typer.Option(
        None,
        "--mode",
        envvar="FLOSH_CAPTURE_MODE",
        help="Capture mode: area, screen, output, active, window.",
    ),
    filename_template: str | None = typer.Option(
        None,
        "--filename-template",
        envvar="FLOSH_FILENAME_TEMPLATE",
        help="strftime filename template for saved screenshots.",
    ),
    root: Path | None = typer.Option(
        None,
        "--root",
        envvar="FLOSH_TARGET_ROOT",
        help="Optional picker boundary when changing target from the menu.",
    ),
    create: bool | None = typer.Option(
        None,
        "--create/--no-create",
        help="Allow creating target directories. Defaults to target.create.",
    ),
    include_hidden: bool = typer.Option(False, "--include-hidden", help="Show hidden directories."),
    picker: str | None = typer.Option(
        None,
        "--picker",
        envvar="FLOSH_PICKER",
        help="Picker backend: auto, fzf, wofi, rofi, stdin.",
    ),
    terminal: str | None = typer.Option(
        None,
        "--terminal",
        envvar="FLOSH_TERMINAL",
        help="Terminal command used when fzf needs a GUI terminal.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Capture once, then choose whether to edit/save directly/change target."""
    settings = capture_settings(
        ctx,
        mode=mode,
        filename_template=filename_template,
        no_swappy=True,
    )
    resolved = resolve_config(ctx_obj(ctx))
    selected_picker = picker or settings.picker
    selected_terminal = terminal or str(get_dotted(resolved.data, "tools.terminal"))
    selected_terminal_class = str(get_dotted(resolved.data, "tools.terminal_class"))
    create_missing = create
    if create_missing is None:
        create_missing = bool(get_dotted(resolved.data, "target.create"))
    selected_root, _ = default_pick_root_and_start(
        resolved,
        explicit_root=root,
        start_current=True,
    )

    try:
        raw_path = capture_raw_screenshot(grimshot=settings.grimshot, mode=settings.mode)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from None

    target_dir = settings.target_dir
    try:
        while True:
            entries = [MENU_EDITOR, MENU_SAVE, MENU_SELECT_DIR, MENU_CANCEL]
            choice = picker_mod.pick_from_menu(
                entries,
                prompt=f"Screenshot action [{target_dir.name or target_dir}]",
                picker=selected_picker,
                terminal=selected_terminal,
            )
            if not choice or choice == MENU_CANCEL:
                notify("Screenshot cancelled")
                raise typer.Exit(1)
            if choice == MENU_SELECT_DIR:
                selected = picker_mod.browse_directory(
                    selected_root,
                    start=target_dir,
                    include_hidden=include_hidden,
                    allow_create=create_missing,
                    picker=selected_picker,
                    terminal=selected_terminal,
                    terminal_class=selected_terminal_class,
                )
                if selected is None:
                    continue
                target_dir = selected
                update_target(state_path(resolved), target_dir, recent_limit=recent_limit(resolved))
                notify("Screenshot target changed", str(target_dir))
                continue
            if choice == MENU_SAVE:
                output = save_raw_capture(
                    raw_path,
                    target_dir=target_dir,
                    filename_template=settings.filename_template,
                )
                notify("Screenshot saved", output.name)
                print_capture_result(output, json_output=json_output)
                return
            if choice == MENU_EDITOR:
                output = open_raw_in_editor(
                    raw_path,
                    target_dir=target_dir,
                    filename_template=settings.filename_template,
                    editor=settings.editor,
                    swappy=settings.swappy,
                    satty=settings.satty,
                )
                notify("Screenshot saved", output.name)
                return
            raise typer.BadParameter(f"unexpected menu choice: {choice}")
    except CaptureCancelled:
        notify("Screenshot cancelled")
        raise typer.Exit(1) from None
    except (RuntimeError, ValueError, FileNotFoundError, NotADirectoryError) as exc:
        raise typer.BadParameter(str(exc)) from None
    finally:
        raw_path.unlink(missing_ok=True)


def paste_settings(
    ctx: typer.Context,
    *,
    backend: Backend | None,
    keymap: Keymap | None,
    wait_s: float | None,
    delay_ms: int | None,
) -> PasteSettings:
    resolved = resolve_config(ctx_obj(ctx))
    selected_backend = backend or str(get_dotted(resolved.data, "paste.backend"))
    if selected_backend not in {"xdotool", "wtype", "ydotool"}:
        raise typer.BadParameter(f"unsupported paste backend: {selected_backend}")
    selected_keymap = keymap or str(get_dotted(resolved.data, "paste.keymap"))
    if selected_keymap not in {"none", "de-us"}:
        raise typer.BadParameter(f"unsupported paste keymap: {selected_keymap}")
    return PasteSettings(
        backend=selected_backend,  # type: ignore[arg-type]
        keymap=selected_keymap,  # type: ignore[arg-type]
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
    keymap: Keymap | None = typer.Option(
        None,
        "--keymap",
        envvar="FLOSH_PASTE_KEYMAP",
        help="Keyboard-layout compensation: none, de-us.",
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
    settings = paste_settings(ctx, backend=backend, keymap=keymap, wait_s=wait_s, delay_ms=delay_ms)
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
    keymap: Keymap | None = typer.Option(
        None,
        "--keymap",
        envvar="FLOSH_PASTE_KEYMAP",
        help="Keyboard-layout compensation: none, de-us.",
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
    settings = paste_settings(ctx, backend=backend, keymap=keymap, wait_s=wait_s, delay_ms=delay_ms)
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
    keymap: Keymap | None = typer.Option(
        None,
        "--keymap",
        envvar="FLOSH_PASTE_KEYMAP",
        help="Keyboard-layout compensation: none, de-us.",
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
    settings = paste_settings(ctx, backend=backend, keymap=keymap, wait_s=wait_s, delay_ms=delay_ms)
    run_paste(sys.stdin.read(), settings)


@ocr_app.command("capture")
def ocr_capture(
    ctx: typer.Context,
    mode: CaptureMode | None = typer.Option(
        None,
        "--mode",
        envvar="FLOSH_CAPTURE_MODE",
        help="Capture mode: area, screen, output, active, window.",
    ),
    lang: str | None = typer.Option(
        None,
        "--lang",
        envvar="FLOSH_OCR_LANG",
        help="Tesseract language list, e.g. deu+eng.",
    ),
    psm: int | None = typer.Option(
        None,
        "--psm",
        envvar="FLOSH_OCR_PSM",
        help="Tesseract page segmentation mode.",
    ),
    preprocess: bool | None = typer.Option(
        None,
        "--preprocess/--no-preprocess",
        help="Preprocess image before OCR. Defaults to ocr.preprocess.",
    ),
    save: bool = typer.Option(False, "--save", help="Also save recognized text as .txt."),
    filename_template: str | None = typer.Option(
        None,
        "--filename-template",
        envvar="FLOSH_FILENAME_TEMPLATE",
        help="strftime filename template for saved OCR text.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Capture an area, run OCR, and copy recognized text to the clipboard."""
    resolved = resolve_config(ctx_obj(ctx))
    selected_mode = mode or str(get_dotted(resolved.data, "capture.default_mode"))
    if selected_mode not in {"area", "screen", "output", "active", "window"}:
        raise typer.BadParameter(f"unsupported capture mode: {selected_mode}")

    settings = OcrSettings(
        target_dir=effective_target(resolved).expanduser(),
        mode=selected_mode,  # type: ignore[arg-type]
        filename_template=filename_template
        if filename_template is not None
        else str(get_dotted(resolved.data, "capture.filename_template")),
        lang=lang if lang is not None else str(get_dotted(resolved.data, "ocr.lang")),
        psm=psm if psm is not None else int(get_dotted(resolved.data, "ocr.psm")),
        preprocess=preprocess
        if preprocess is not None
        else bool(get_dotted(resolved.data, "ocr.preprocess")),
        keep_preprocessed=bool(get_dotted(resolved.data, "ocr.keep_preprocessed")),
        grimshot=str(get_dotted(resolved.data, "tools.grimshot")),
        tesseract=str(get_dotted(resolved.data, "tools.tesseract")),
        magick=str(get_dotted(resolved.data, "tools.magick")),
        wl_copy=str(get_dotted(resolved.data, "tools.wl_copy")),
    )
    try:
        text, preprocessed_path = capture_ocr_text(settings)
        copy_text_to_clipboard(text, wl_copy=settings.wl_copy)
        saved_path = (
            save_ocr_text(
                text,
                target_dir=settings.target_dir,
                filename_template=settings.filename_template,
            )
            if save
            else None
        )
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from None

    notify("OCR copied", f"{len(text)} chars")
    if json_output:
        payload = {
            "chars": len(text),
            "destination": "clipboard",
            "saved_path": str(saved_path) if saved_path is not None else None,
            "preprocessed_path": str(preprocessed_path) if preprocessed_path is not None else None,
        }
        typer.echo(json.dumps(payload, sort_keys=True))
    elif save and saved_path is not None:
        typer.echo(saved_path)
