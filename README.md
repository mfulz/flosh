# flosh

`flosh` is a small Wayland-first workflow CLI for screenshot target management,
swappy-based captures, and clipboard-to-keyboard typing.

It is intentionally CLI-first: Sway bindings, Waybar modules, a future tray icon,
or a future overlay should call the same commands instead of reimplementing the
workflow logic.

Current primary target: **Sway / wlroots / Wayland**.

## Current status

Implemented and usable now:

- config file loading and editing
- profile and environment overrides
- active screenshot target state
- interactive target picker (`wofi`, `rofi`, `fzf`, or stdin fallback)
- swappy screenshot flow
- direct no-swappy screenshot output to clipboard or file
- typing clipboard/text/stdin into the focused app (`xdotool`, `wtype`, `ydotool`)

Planned, not implemented yet:

- OCR capture flow
- GUI/tray/layer-shell overlay
- native screenshot backend abstraction beyond the current grimshot-based path

## Runtime model

`flosh` separates **configuration** from **state**.

Configuration is reproducible:

- capture mode
- filename template
- picker backend
- paste backend
- tool paths

State is dynamic:

- current active capture target directory
- recent capture target directories

Precedence is deterministic:

```text
CLI argument > environment variable > profile > config file > built-in default
```

## Installation

Development checkout with `uv`:

```bash
git clone https://github.com/mfulz/flosh.git
cd flosh
uv sync --extra dev
uv run flosh --help
```

Editable install with pip:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Expected system tools for the current Sway/Wayland workflow:

```bash
sudo pacman -S --needed grim slurp swappy wl-clipboard xdotool fzf wofi
```

Only tools needed by the command being used are required at runtime.

## Command overview

```bash
flosh config ...   inspect and manage config files
flosh target ...   inspect and manage the active capture target directory
flosh take ...     capture screenshots and route save/edit flows
flosh paste ...    type clipboard or text into focused applications
flosh ocr ...      placeholder for future OCR flow
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

Default user config path:

```text
~/.config/flosh/config.toml
```

Default user state path:

```text
~/.local/state/flosh/state.toml
```

Create a starter config:

```bash
flosh config init
```

Create or operate on an explicit config:

```bash
flosh --config ./flosh.toml config init
flosh --config ./flosh.toml config show
```

Example config:

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
create = false
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
terminal = "alacritty"
```

Profiles are nested below `[profiles.<name>]`:

```toml
[profiles.work.target]
root = "~/Work/PRIVATE"

[profiles.citrix.paste]
backend = "xdotool"
wait_s = 1.0
delay_ms = 100
```

Use a profile:

```bash
flosh --profile citrix paste clipboard
FLOSH_PROFILE=citrix flosh paste clipboard
```

## Environment variables

Common overrides:

```bash
FLOSH_CONFIG=./flosh.toml
FLOSH_PROFILE=work
FLOSH_VERBOSE=1
FLOSH_CAPTURE_MODE=area
FLOSH_CAPTURE_DESTINATION=clipboard
FLOSH_CAPTURE_SAVE_DIR=/tmp/screens
FLOSH_FILENAME_TEMPLATE='%Y-%m-%d_%H-%M-%S.png'
FLOSH_TARGET_ROOT=/home/mfulz/Work/PRIVATE
FLOSH_TARGET_START=current
FLOSH_TARGET_CREATE=false
FLOSH_PICKER=fzf
FLOSH_TERMINAL=alacritty
FLOSH_PASTE_BACKEND=xdotool
FLOSH_PASTE_WAIT_S=2
FLOSH_PASTE_DELAY_MS=80
FLOSH_STATE_PATH=/tmp/flosh-state.toml
```

## Config commands

Print config path:

```bash
flosh config path
```

Show effective merged config:

```bash
flosh config show
flosh config show --format toml
flosh config show --format json
flosh config show --sources
```

Get or set a value:

```bash
flosh config get capture.default_mode
flosh config set capture.default_mode area
```

Edit in `$EDITOR`:

```bash
flosh config edit
```

## Target commands

The target directory is the active destination for screenshot saves. It is stored
as state, not as static config.

Show target:

```bash
flosh target show
flosh target show --short
flosh target show --json
flosh target show --json --text-mode compact --max-length 80
flosh target show --json --text-mode basename
flosh target show --json --text-mode path --max-length 0
```

JSON output is generic enough for status bars such as Waybar. The `tooltip`
contains the relevant runtime configuration so hovering the module shows what
config/profile/state and defaults are active:

```json
{
  "alt": "/home/mfulz/Pictures/Screenshots",
  "class": ["flosh-target", "exists"],
  "text": "~/Pictures/Screenshots",
  "tooltip": "flosh\ntarget: /home/mfulz/Pictures/Screenshots\nconfig: /home/mfulz/.config/flosh/config.toml\nprofile: default\nstate: /home/mfulz/.local/state/flosh/state.toml\n\ncapture\n  mode: area\n  destination: clipboard\n  filename: %Y-%m-%d_%H-%M-%S.png\n  picker: auto\n\ntarget picker\n  root: /home/mfulz/Pictures\n  start: current\n  create: False\n\npaste\n  backend: xdotool\n  wait_s: 2.0\n  delay_ms: 80"
}
```

Set target:

```bash
flosh target set ~/Pictures/Screenshots
flosh target set ~/Pictures/Screenshots --create
flosh target set /tmp/screens --print-only
```

Pick target interactively:

```bash
flosh target pick
```

Current behavior:

- without `--root`, picker boundary is `/`
- start directory is controlled by `target.start`
- default `target.start = "current"` starts at the persisted target state
- `target.start = "root"` starts at `target.root`
- this allows moving out to `/tmp`, `/home`, etc. unless `--root` is used
- with `--root`, picker is explicitly constrained below that root

Examples:

```bash
flosh target pick --picker fzf
flosh target pick --root ~/Work/PRIVATE --create
flosh target pick --root ~/Work/PRIVATE --no-create
flosh target pick --root ~/Work/PRIVATE --start-current --create --picker fzf
flosh target pick --no-start-current --picker fzf
```

Picker navigation model:

```text
✔ Select this directory
../
child-directory/
+ Create new folder here
```

Picker backend selection:

```bash
flosh target pick --picker auto
flosh target pick --picker fzf
flosh target pick --picker wofi
flosh target pick --picker rofi
flosh target pick --picker stdin
```

When `--picker fzf` is used without an attached TTY, `flosh` opens a terminal
(default: `alacritty`) and runs `fzf` there. Override it with:

```bash
flosh target pick --picker fzf --terminal alacritty
FLOSH_TERMINAL=alacritty flosh target pick --picker fzf
```

Directory creation can be controlled by CLI, config, or environment:

```bash
flosh config set target.create true
FLOSH_TARGET_CREATE=true flosh target pick --picker fzf
```

Typed paths are supported:

```text
/tmp/some-existing-directory      selects that directory
/tmp/new-directory + --create     creates and selects it
relative/path + --create          creates below the current picker directory
```

## Screenshot commands

### Swappy flow

Default screenshot command:

```bash
flosh take
```

Current behavior:

1. capture a raw screenshot via `grimshot`
2. open `swappy`
3. pass an output path with `-o` pointing at the active target directory
4. keep stdout/stderr quiet by default
5. show a desktop notification after swappy exits successfully

Conceptually:

```bash
grimshot save area /tmp/flosh-capture-XXXX.png
swappy -f /tmp/flosh-capture-XXXX.png -o "$ACTIVE_TARGET/filename.png"
```

Capture modes:

```bash
flosh take --mode area
flosh take --mode screen
flosh take --mode output
flosh take --mode active
flosh take --mode window
```

### Direct output without swappy

Use `--no-swappy` when `flosh` itself should decide the output destination.

Default direct destination is `capture.default_destination`, currently
`clipboard`.

```bash
flosh take --no-swappy
flosh take --no-swappy --clipboard
flosh take --no-swappy --save
```

Make direct file output the default for `--no-swappy`:

```bash
flosh config set capture.default_destination file
```

Or for one process:

```bash
FLOSH_CAPTURE_DESTINATION=file flosh take --no-swappy
```

Machine-readable output is only printed when requested:

```bash
flosh take --no-swappy --save --json
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

Notes:

- `Edit/save in swappy` opens swappy with `-o` set to the active target path.
- `Save screenshot directly` saves the already captured raw screenshot without swappy.
- `Select/change target directory` changes target state before choosing another action.
- OCR menu entries are planned later.

## Paste commands

Paste commands type text into the focused application. They do not ask the target
application to paste from its clipboard.

This is useful for Citrix/Wfica and similar environments where normal clipboard
paste is disabled or unreliable.

Type current Wayland clipboard into the focused app:

```bash
flosh paste clipboard
```

Recommended for Citrix/Wfica running as XWayland:

```bash
flosh paste clipboard --backend xdotool --wait-s 2 --delay-ms 80
```

Type literal text:

```bash
flosh paste text 'hello world'
```

Type stdin:

```bash
printf 'hello world\n' | flosh paste stdin
```

Backends:

```bash
flosh paste clipboard --backend xdotool
flosh paste clipboard --backend wtype
flosh paste clipboard --backend ydotool
```

Current practical default is `xdotool`, because Citrix/Wfica as XWayland was
tested with `xdotool`, while `wtype` produced incorrect input in that target.

## OCR commands

OCR is not implemented yet. The placeholder command exists:

```bash
flosh ocr capture
```

Planned behavior:

- capture image
- optionally preprocess with ImageMagick
- OCR with `tesseract`
- copy or type recognized text
- optionally save intermediate images for debugging

## Waybar integration

Waybar does not need a dedicated `flosh waybar` command. Use generic JSON output
from `flosh target show --json` and keep Waybar-specific wiring in a module
asset/snippet.

A ready-to-copy example lives at:

```text
examples/waybar/flosh-target.json
```

Current example:

```json
"custom/flosh-target": {
  "exec": "flosh target show --json --text-mode compact --max-length 80",
  "return-type": "json",
  "interval": "once",
  "signal": 8,
  "on-click": "flosh take",
  "on-click-right": "sh -c 'flosh target pick --picker fzf --terminal alacritty && pkill -RTMIN+8 waybar'"
}
```

Meaning:

- module text shows the active target path from state
- left click takes a screenshot with the configured default flow
- right click opens the target picker
- after a successful target pick, Waybar receives `RTMIN+8` and refreshes the
  module immediately

Take screenshot as a separate button if wanted:

```json
"custom/flosh-shot": {
  "format": "",
  "tooltip": "Take screenshot",
  "on-click": "flosh take"
}
```

Type clipboard into focused window as a separate button if wanted:

```json
"custom/flosh-paste": {
  "format": "󰅍",
  "tooltip": "Type clipboard into focused window",
  "on-click": "flosh paste clipboard --backend xdotool --wait-s 1 --delay-ms 80"
}
```

## Sway integration

Screenshot via swappy:

```sway
bindsym $mod+p exec "$HOME/.local/bin/flosh take"
```

Screenshot menu:

```sway
bindsym $mod+Shift+p exec "$HOME/.local/bin/flosh take menu"
```

Type clipboard into focused app:

```sway
bindsym $mod+Shift+v exec "$HOME/.local/bin/flosh paste clipboard --backend xdotool --wait-s 2 --delay-ms 80"
```

Pick target directory:

```sway
bindsym $mod+Ctrl+p exec "sh -c '$HOME/.local/bin/flosh target pick --picker fzf --terminal alacritty && pkill -RTMIN+8 waybar'"
```

## Migration from shotdir

| shotdir | flosh |
| --- | --- |
| `shotdir --show` | `flosh target show` |
| `shotdir --set PATH` | `flosh target set PATH` |
| `shotdir --pick-under ROOT --create` | `flosh target pick --root ROOT --create` |
| `shotdir --take` | `flosh take` |
| `shotdir --take --no-swappy` | `flosh take --no-swappy --save` |
| `shotdir --menu` | `flosh take menu` |
| `shotdir --ocr` | planned: `flosh ocr capture` |

## Development

Run from checkout:

```bash
uv run flosh --help
```

Lint and type check:

```bash
uv run ruff check .
uv run mypy src
```

## License

MIT.
