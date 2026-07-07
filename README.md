# flosh

`flosh` is a small Wayland-first workflow CLI for screenshot target management,
annotated captures, OCR, and clipboard-to-keyboard typing.

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
- Satty screenshot annotation flow
- direct no-swappy screenshot output to clipboard or file
- typing clipboard/text/stdin into the focused app (`xdotool`, `wtype`, `ydotool`)
- OCR area capture to clipboard, optionally saved as `.txt`

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
sudo pacman -S --needed grim slurp satty wl-clipboard xdotool fzf wofi
```

Only tools needed by the command being used are required at runtime.

## Command overview

```bash
flosh config ...   inspect and manage config files
flosh target ...   inspect and manage the active capture target directory
flosh take ...     capture screenshots and route save/edit flows
flosh paste ...    type clipboard or text into focused applications
flosh ocr ...      capture screen text with OCR
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
editor = "satty"
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
satty = "satty"
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

### Editor flow

Default screenshot command:

```bash
flosh take
```

Current default editor is `satty` because its save/cancel semantics are explicit:
`--output-filename` is used for the save action, while Escape is configured to
exit without saving.

Current behavior:

1. capture a raw screenshot via `grimshot`
2. open the configured editor (`capture.editor`, default: `satty`)
3. pass the active target output path to Satty as its save filename
4. keep stdout/stderr quiet by default
5. show a desktop notification after a successful save

Conceptually:

```bash
grimshot save area /tmp/flosh-capture-XXXX.png
satty --filename /tmp/flosh-capture-XXXX.png \
  --output-filename "$ACTIVE_TARGET/filename.png" \
  --actions-on-escape exit \
  --early-exit save
```

Capture modes:

```bash
flosh take --mode area
flosh take --mode screen
flosh take --mode output
flosh take --mode active
flosh take --mode window
```

Swappy can still be selected explicitly, but it cannot reliably report the saved
path to flosh without using `-o`, and `swappy -o` exports on exit, which breaks
Escape-as-cancel semantics. Prefer Satty for flosh-managed saves.

```bash
flosh config set capture.editor satty
FLOSH_CAPTURE_EDITOR=satty flosh take
```

### Direct output without editor

Use `--no-swappy` when `flosh` itself should decide the output destination and no
annotation editor should be opened. The flag keeps the old public name for now,
but semantically means “no editor”.

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
Edit/save in editor
Save screenshot directly
Select/change target directory
Cancel
```

Notes:

- `Edit/save in editor` opens the configured editor against the already captured raw screenshot.
- `Save screenshot directly` saves the already captured raw screenshot without an editor.
- `Select/change target directory` changes target state before choosing another action.
- OCR is intentionally separate as `flosh ocr capture`.

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

OCR is intentionally capture-focused: select an area, recognize text, and copy the
recognized text to the clipboard. This keeps the common flow tiny and predictable.

```bash
flosh ocr capture
flosh ocr capture --mode area
flosh ocr capture --lang deu+eng --psm 6
flosh ocr capture --no-preprocess
flosh ocr capture --json
```

Save recognized text as `.txt` in the active target directory as well:

```bash
flosh ocr capture --save
flosh ocr capture --save --filename-template '%Y-%m-%d_%H-%M-%S.png'
```

Behavior:

- capture image with the configured `grimshot` backend
- optionally preprocess with ImageMagick (`ocr.preprocess`)
- OCR with `tesseract`
- copy recognized text to the clipboard via `wl-copy`
- optionally save recognized text as `.txt`

## Waybar integration

Waybar does not need a dedicated `flosh waybar` command. Use generic JSON output
from `flosh target show --json` and keep Waybar-specific wiring in a module
asset/snippet.

Ready-to-copy examples live at:

```text
examples/waybar/flosh-target.json
examples/waybar/flosh-shot.json
examples/waybar/flosh-ocr.json
examples/waybar/flosh-paste.json
examples/waybar/modules.json
```

Current example:

```json
"custom/flosh-target": {
  "exec": "flosh target show --json --text-mode compact --max-length 80",
  "return-type": "json",
  "interval": "once",
  "signal": 8,
  "tooltip": true,
  "on-click": "flosh take",
  "on-click-right": "sh -c 'flosh target pick --start-current --picker fzf --terminal alacritty && pkill -RTMIN+8 waybar'"
}
```

Meaning:

- module text shows the active target path from state
- hover tooltip shows the active flosh runtime config
- left click takes a screenshot with the configured default flow
- right click opens the target picker
- after a successful target pick, Waybar receives `RTMIN+8` and refreshes the
  module immediately

Take screenshot as a separate text+icon button if wanted:

```json
"custom/flosh-shot": {
  "format": " Shot",
  "tooltip": "Take screenshot",
  "on-click": "flosh take"
}
```

OCR and paste can also be represented as text+icon buttons:

```json
"custom/flosh-ocr": {
  "format": "󰈙 OCR",
  "tooltip": "OCR capture",
  "on-click": "flosh ocr capture --mode area",
  "on-click-right": "flosh ocr capture --mode area --save"
},
"custom/flosh-paste": {
  "format": "󰅍 Paste",
  "tooltip": "Type clipboard into focused window",
  "on-click": "flosh paste clipboard --backend xdotool --wait-s 1 --delay-ms 80"
}
```

## Sway integration

Screenshot via configured editor:

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
bindsym $mod+Ctrl+p exec "sh -c '$HOME/.local/bin/flosh target pick --start-current --picker fzf --terminal alacritty && pkill -RTMIN+8 waybar'"
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
| `shotdir --ocr` | `flosh ocr capture` |

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
