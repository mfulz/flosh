# flosh

`flosh` is a Wayland-first workflow tool for screenshots, capture targets, OCR,
and clipboard-to-keyboard typing.

It starts as a robust CLI backend and is intentionally designed so a later tray
icon, Waybar integration, or layer-shell overlay can call the same stable commands
instead of reimplementing the workflow logic.

The name is short for **flowshot**: capture and text flows around screenshots,
clipboard content, OCR, and focused application input.

## Goals

`flosh` is built for keyboard-heavy Linux/Wayland workflows where screenshots are
not just images. A capture might become:

- a saved screenshot in the current project/workspace directory
- an image opened in an editor such as `swappy`
- OCR text copied to the Wayland clipboard
- OCR text typed into a focused application
- clipboard text typed into an XWayland-only application such as Citrix/Wfica
- a Waybar-visible state value such as the current capture target directory

The first implementation target is Sway/Wayland, but the core concepts are not
Sway-specific.

## Non-goals for the first release

The first release is not intended to be a full graphical screenshot editor. It
will orchestrate existing mature tools first:

- `grim` / `grimshot` / `slurp` for capture
- `swappy` for annotation/editing
- `tesseract` and ImageMagick for OCR
- `wl-copy` / `wl-paste` for Wayland clipboard I/O
- `xdotool` for typing into XWayland applications
- optionally later: `wtype` or `ydotool` as typing backends

A tray icon or overlay UI is planned later, after the CLI and config model are
stable.

## Design principles

### CLI first, GUI later

Every important action must be available as a stable CLI command. A GUI, tray
icon, or Waybar button should only call these commands or the same Python core
API.

### Config and state are separate

Configuration is reproducible and can live in a project/workspace context.
State is dynamic and can change during daily use.

Examples:

- config: default capture mode, OCR language, preferred picker, typing backend
- state: active capture target directory, recent target directories

This separation allows context-driven setups such as ROBA/workspace configs
without constantly dirtying committed configuration files when only the current
screenshot target changes.

### Deterministic precedence

For every setting, resolution order is:

```text
CLI argument > environment variable > config file > built-in default
```

This is intentionally boring and inspectable. It allows the same config file to
be reused while a systemd user service, Waybar module, or ROBA context overrides
only one value via environment.

### Multiple config files are first-class

`flosh` supports explicit config selection:

```bash
flosh --config ./flosh.toml target show
```

or via environment:

```bash
FLOSH_CONFIG=./flosh.toml flosh target show
```

This makes per-workspace configuration a normal workflow rather than a hack.

## Installation

Development checkout:

```bash
git clone https://github.com/mfulz/flosh.git
cd flosh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

With `uv`:

```bash
git clone https://github.com/mfulz/flosh.git
cd flosh
uv sync --extra dev
uv run flosh --help
```

System tools expected for full functionality on Sway/Wayland:

```bash
sudo pacman -S --needed grim slurp swappy wl-clipboard xdotool tesseract imagemagick fzf wofi
```

Only the tools needed for the command being used are required at runtime.

## Command overview

```bash
flosh --help
```

Planned top-level command groups:

```text
flosh config ...   inspect and manage config files
flosh target ...   inspect and manage the active capture target directory
flosh take ...     capture screenshots and route save/edit flows
flosh paste ...    type clipboard or text into focused applications
flosh ocr ...      capture and OCR screen content
```

Global options:

```bash
flosh --config ./flosh.toml --profile work --verbose <command>
```

Equivalent environment overrides:

```bash
FLOSH_CONFIG=./flosh.toml FLOSH_PROFILE=work FLOSH_VERBOSE=1 flosh <command>
```

## Configuration

### Default config paths

User config path, following XDG conventions via `platformdirs`:

```text
~/.config/flosh/config.toml
```

User state path:

```text
~/.local/state/flosh/state.toml
```

Both paths can be overridden.

### Example config

```toml
[capture]
default_mode = "area"
default_destination = "clipboard"
filename_template = "%Y-%m-%d_%H-%M-%S.png"
save_dir = "~/Pictures/Screenshots"
editor = "swappy"
picker = "auto"

[target]
root = "~/Pictures"
start = "current"
recent_limit = 20

[paste]
backend = "xdotool"
wait_s = 2.0
delay_ms = 80
restore_clipboard = false

[ocr]
lang = "deu+eng"
psm = 6
preprocess = true
keep_preprocessed = false

[tools]
grimshot = "grimshot"
grim = "grim"
slurp = "slurp"
swappy = "swappy"
wl_copy = "wl-copy"
wl_paste = "wl-paste"
xdotool = "xdotool"
wtype = "wtype"
ydotool = "ydotool"
tesseract = "tesseract"
magick = "magick"
```

### Profiles

A config file may contain named profiles:

```toml
[profiles.work.capture]
save_dir = "~/Work/PRIVATE/screenshots"

[profiles.citrix.paste]
backend = "xdotool"
wait_s = 1.0
delay_ms = 100
```

Use a profile:

```bash
flosh --profile citrix paste clipboard
```

or:

```bash
FLOSH_PROFILE=citrix flosh paste clipboard
```

Profile values override base config values but are still overridden by env and
CLI arguments.

## Environment variable mapping

Every commonly used option should have an environment override. Names are stable
and prefixed with `FLOSH_`.

Examples:

```bash
FLOSH_CONFIG=./flosh.toml
FLOSH_PROFILE=citrix
FLOSH_CAPTURE_SAVE_DIR=/tmp/screens
FLOSH_CAPTURE_MODE=area
FLOSH_TARGET_ROOT=/home/mfulz/Work/PRIVATE
FLOSH_PICKER=fzf
FLOSH_PASTE_BACKEND=xdotool
FLOSH_PASTE_WAIT_S=2
FLOSH_PASTE_DELAY_MS=80
FLOSH_OCR_LANG=deu+eng
```

## Config commands

### Print the effective config path

```bash
flosh config path
```

With explicit config:

```bash
flosh --config ./flosh.toml config path
```

### Show merged effective configuration

```bash
flosh config show
```

Show as TOML:

```bash
flosh config show --format toml
```

Show as JSON:

```bash
flosh config show --format json
```

Show where values came from:

```bash
flosh config show --sources
```

This should help debug precedence:

```text
capture.save_dir = /tmp/screens    source=env:FLOSH_CAPTURE_SAVE_DIR
paste.delay_ms = 80                source=config:/home/.../config.toml
```

### Create a starter config

```bash
flosh config init
```

Create at an explicit path:

```bash
flosh --config ./flosh.toml config init
```

Overwrite existing file explicitly:

```bash
flosh config init --force
```

### Get a config value

```bash
flosh config get capture.save_dir
```

### Set a config value

```bash
flosh config set capture.save_dir ~/Pictures/Screenshots
```

Set in a workspace config:

```bash
flosh --config ./flosh.toml config set capture.save_dir ./screenshots
```

### Edit config in `$EDITOR`

```bash
flosh config edit
```

## Target directory commands

The target directory is the active save destination for screenshot/capture
commands. It is state by default, not static config.

### Show current target

```bash
flosh target show
```

Short display for Waybar:

```bash
flosh target show --short
```

JSON output for status bars:

```bash
flosh target show --json
```

Expected JSON shape:

```json
{
  "text": "screenshots",
  "tooltip": "/home/mfulz/Pictures/Screenshots",
  "class": "flosh-target"
}
```

### Set current target

```bash
flosh target set ~/Pictures/Screenshots
```

Create if missing:

```bash
flosh target set ~/Pictures/Screenshots --create
```

Use without writing state, useful in scripts:

```bash
flosh target set /tmp/screens --print-only
```

### Pick current target interactively

Use configured root:

```bash
flosh target pick
```

Use explicit root:

```bash
flosh target pick --root ~/Work/PRIVATE
```

Allow creating directories:

```bash
flosh target pick --root ~/Work/PRIVATE --create
```

Start browsing at current target instead of root:

```bash
flosh target pick --root ~/Work/PRIVATE --start-current
```

Force picker:

```bash
flosh target pick --picker fzf
flosh target pick --picker wofi
flosh target pick --picker rofi
```

The picker should support this navigation model:

```text
✔ Select this directory
../
child-directory/
+ Create new folder here
```

## Screenshot commands

### Take using defaults

```bash
flosh take
```

By default this captures an image and opens it in `swappy` with `-o` pointing at
the active target directory. Swappy remains the interactive UI; flosh only
provides the suggested output path.

### Capture modes

```bash
flosh take --mode area
flosh take --mode screen
flosh take --mode output
flosh take --mode active
flosh take --mode window
```

### Direct output without swappy

Use `--no-swappy` when flosh itself should decide where the image goes. The
default direct destination is configurable and currently defaults to clipboard.

```bash
flosh take --no-swappy
flosh take --no-swappy --clipboard
flosh take --no-swappy --save
```

To make direct file output the default for `--no-swappy` in a config/profile:

```bash
flosh config set capture.default_destination file
```

Or for one process environment:

```bash
FLOSH_CAPTURE_DESTINATION=file flosh take --no-swappy
```

### Menu flow

```bash
flosh take menu
```

Current menu entries:

```text
Edit/save in swappy
Save screenshot directly
Select/change target directory
Cancel
```

OCR actions are planned as a follow-up once the capture core is stable. Later
this can become a tray or overlay menu without changing the backend commands.

## Paste commands

Paste commands do not use the clipboard protocol to paste into the target app.
They read text and type it as keyboard input.

This is useful for applications such as Citrix/Wfica where normal clipboard
paste may be disabled or unreliable.

### Type current clipboard into focused app

```bash
flosh paste clipboard
```

Recommended for Citrix/Wfica running as XWayland:

```bash
flosh paste clipboard --backend xdotool --wait-s 2 --delay-ms 80
```

The delay gives time to focus the target field. The per-character delay makes
Citrix less likely to drop or mangle input.

Environment overrides:

```bash
FLOSH_PASTE_BACKEND=xdotool FLOSH_PASTE_WAIT_S=2 FLOSH_PASTE_DELAY_MS=80 flosh paste clipboard
```

### Type literal text

```bash
flosh paste text 'hello world'
```

### Type stdin

```bash
printf 'hello world\n' | flosh paste stdin
```

### Backend selection

```bash
flosh paste clipboard --backend xdotool
flosh paste clipboard --backend wtype
flosh paste clipboard --backend ydotool
```

Initial default should be `xdotool` because Citrix/Wfica as XWayland was tested
to work with `xdotool`, while `wtype` produced incorrect input in that target.

## OCR commands

OCR can be implemented after the initial target/take/paste core is stable.

### Capture and copy OCR text

```bash
flosh ocr capture --copy
```

### Capture and type OCR text into focused app

```bash
flosh ocr capture --type --backend xdotool --wait-s 2 --delay-ms 80
```

### Capture, copy, and save image

```bash
flosh ocr capture --copy --save-image
```

### OCR options

```bash
flosh ocr capture --lang deu+eng --psm 6
flosh ocr capture --no-preprocess
flosh ocr capture --keep-preprocessed
```

## Waybar integration

### Show active capture target

Example Waybar module:

```json
"custom/flosh-target": {
  "exec": "flosh target show --json",
  "return-type": "json",
  "interval": 5,
  "on-click": "flosh target pick --root /home/mfulz/Work/PRIVATE --start-current --create --picker fzf"
}
```

### Type clipboard into Citrix/Wfica

```json
"custom/flosh-paste": {
  "format": "󰅍",
  "tooltip": "Type clipboard into focused window",
  "on-click": "flosh paste clipboard --backend xdotool --wait-s 1 --delay-ms 80"
}
```

### Take screenshot

```json
"custom/flosh-shot": {
  "format": "",
  "tooltip": "Take screenshot",
  "on-click": "flosh take menu"
}
```

## Sway integration

Existing `shotdir` style bindings can migrate to `flosh`.

Take screenshot directly:

```sway
bindsym $mod+p exec "$HOME/.local/bin/flosh take"
```

Open menu:

```sway
bindsym $mod+Shift+p exec "$HOME/.local/bin/flosh take menu"
```

Type clipboard into focused app, useful for Citrix/Wfica:

```sway
bindsym $mod+Shift+v exec "$HOME/.local/bin/flosh paste clipboard --backend xdotool --wait-s 2 --delay-ms 80"
```

Change target directory via picker:

```sway
bindsym $mod+Ctrl+p exec "$HOME/.local/bin/flosh target pick --root /home/mfulz/Work/PRIVATE --start-current --create --picker fzf"
```

## Migration from `shotdir`

Existing `shotdir` features to migrate first:

| shotdir | flosh target |
| --- | --- |
| `shotdir --show` | `flosh target show` |
| `shotdir --set PATH` | `flosh target set PATH` |
| `shotdir --pick-under ROOT --create` | `flosh target pick --root ROOT --create` |
| `shotdir --take` | `flosh take` |
| `shotdir --take --no-swappy` | `flosh take --no-swappy --save` |
| `shotdir --ocr` | `flosh ocr capture --copy` |
| `shotdir --menu` | `flosh take menu` |

New feature:

```bash
flosh paste clipboard --backend xdotool
```

## Implementation plan

### Phase 1: CLI skeleton and config model

- Typer app and command groups
- config path resolution
- TOML config loading
- profile merge
- env var overrides
- `flosh config path/show/init/get/set/edit`

### Phase 2: target state and picker

- state file for active target directory
- `target show/set/pick`
- picker backends: auto, fzf, wofi, rofi, stdin
- recent target tracking
- Waybar JSON output

### Phase 3: paste backend

- `paste clipboard`
- `paste text`
- `paste stdin`
- backend `xdotool`
- optional later backends: `wtype`, `ydotool`

### Phase 4: screenshot capture

- migrate shotdir capture/save/swappy flow
- `take` and `take menu`
- target state integration

Implemented baseline:

- `flosh take` opens swappy with `-o` set to the active target path
- `flosh take --no-swappy` direct clipboard/file output
- `flosh take --no-swappy --save`
- `flosh take menu` with save/swappy/target-change/cancel

### Phase 5: OCR

- migrate OCR preprocessing and tesseract flow
- copy/type/save variants

### Phase 6: GUI/tray/overlay

- small tray or Wayland layer-shell frontend
- no new workflow logic in the GUI
- buttons call stable CLI/core functions

## Development

Run from checkout:

```bash
uv run flosh --help
```

Run linting:

```bash
uv run ruff check .
```

Run type checking:

```bash
uv run mypy src
```

## License

MIT.
