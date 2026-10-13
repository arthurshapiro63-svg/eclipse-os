"""Plain names for keybinds made in Lua.

Hyprland's Lua config registers every bind as a Lua function, so `hyprctl binds` only says
`__lua 12` for each one. This reads the Lua config files, finds each `hl.bind(COMBO, ACTION)` and
turns the action into a short plain sentence ("Open the terminal", "Go to workspace 3"), keyed by
the normalised combo, so Settings > Keybinds (and the AI) can show what a key does.
"""
import re
from pathlib import Path

MODS = ("SUPER", "CTRL", "ALT", "SHIFT")
_BIND = re.compile(r'hl\.bind\(\s*(.+?)\s*,\s*(hl\.dsp\..*)$')
_LOCAL = re.compile(r'^\s*local\s+(\w+)\s*=\s*"([^"]*)"')
_LOOP = re.compile(r'^\s*for\s+(\w+)\s*=\s*\d+\s*,\s*\d+\s+do')

# commands -> words (first match wins; matched against the expanded command)
COMMANDS = [
    (r"arclight-ask --voice", "Ask the AI by voice"),
    (r"arclight-ask --selection", "Ask the AI about the selected text"),
    (r"arclight-ask", "Ask the AI"),
    (r"arclight-settings", "Open Settings"),
    (r"arclight-store", "Open the Store"),
    (r"arc totality", "Totality on / off (focus mode)"),
    (r"arc game mode", "Totality on / off (focus mode)"),
    (r"eclipse-ai", "Open Eclipse AI"),
    (r"arch-ai-toggle", "Open Arch AI"),
    (r"(claude-orange|arclight-stop) --stop|arclight-stop", "Stop everything the AI is doing"),
    (r"\b(ghostty|kitty|alacritty|foot)\b", "Open the terminal"),
    (r"\b(thunar|nautilus|dolphin|nemo)\b", "Open files"),
    (r"zen-browser|firefox|chromium", "Open the web browser"),
    (r"zeditor|\bzed\b|code\b", "Open the code editor"),
    (r"shellctl launcher|wofi --show drun|rofi", "Open the app launcher"),
    (r"shellctl overview", "Show all windows"),
    (r"shellctl clipboard", "Clipboard history"),
    (r"shellctl wallpaper", "Pick a wallpaper"),
    (r"wallpaper next", "Next wallpaper"),
    (r"shellctl power|powermenu", "Power menu (log out, restart, shut down)"),
    (r"hyprlock", "Lock the screen"),
    (r"hyprshutdown|hl\.dsp\.exit", "Log out"),
    (r"shot region", "Screenshot of an area"),
    (r"shot full", "Screenshot of the whole screen"),
    (r"shot annotate", "Screenshot and draw on it"),
    (r"shot menu", "Screenshot menu"),
    (r"shot window", "Screenshot of a window"),
    (r"set-volume .*\+", "Volume up"),
    (r"set-volume .*-", "Volume down"),
    (r"set-mute @DEFAULT_AUDIO_SOURCE@", "Microphone mute on / off"),
    (r"set-mute", "Sound mute on / off"),
    (r"brightnessctl .*\+", "Screen brighter"),
    (r"brightnessctl .*-", "Screen darker"),
    (r"playerctl next", "Next track"),
    (r"playerctl previous", "Previous track"),
    (r"playerctl play-pause", "Play / pause"),
]


def norm(combo):
    """'mainMod + shift + q' / 'SUPER + SHIFT + Q' -> 'ALT?CTRL?SHIFT SUPER|q' (order-free, key case-free)."""
    parts = [p.strip() for p in str(combo).split("+") if p.strip()]
    mods = sorted(p.upper() for p in parts if p.upper() in MODS)
    keys = [p for p in parts if p.upper() not in MODS]
    return " ".join(mods) + "|" + (keys[-1].lower() if keys else "")


def strip_comment(line):
    """Drop a trailing Lua `-- comment` (but not `--` inside a string, like "arclight-ask --voice")."""
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q and line[i - 1] != "\\":
                q = None
        elif ch in "\"'":
            q = ch
        elif line.startswith("--", i):
            return line[:i].rstrip()
    return line


def _expand(expr, env):
    """Evaluate a Lua string expression made of "literals", known locals and `..`."""
    out = []
    for tok in re.findall(r'"[^"]*"|[A-Za-z_]\w*|\(.*?\)', expr):
        if tok.startswith('"'):
            out.append(tok[1:-1])
        elif tok in env:
            out.append(env[tok])
        else:
            out.append("{" + tok + "}")
    return "".join(out)


def describe_action(action, env, loopvar=None):
    a = action
    if a.startswith("hl.dsp.exec_cmd("):
        inner = a[len("hl.dsp.exec_cmd("):]
        # up to the matching close paren
        depth, end = 1, len(inner)
        for i, ch in enumerate(inner):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        cmd = _expand(inner[:end], env)
        for pat, words in COMMANDS:
            if re.search(pat, cmd):
                return words
        prog = cmd.split()[0].rsplit("/", 1)[-1] if cmd.split() else cmd
        return f"Run {prog}"
    ws = re.search(r'workspace\s*=\s*("?)([^",}\s]+)\1', a)
    wsv = ws.group(2) if ws else None
    if wsv == loopvar and loopvar:
        wsv = "{n}"
    if a.startswith("hl.dsp.window.close"):
        return "Close the window"
    if a.startswith("hl.dsp.window.float"):
        return "Float / tile the window"
    if a.startswith("hl.dsp.window.fullscreen"):
        return "Full screen on / off"
    if a.startswith("hl.dsp.window.pseudo"):
        return "Keep the window's own size"
    if a.startswith("hl.dsp.window.drag"):
        return "Move a window with the mouse"
    if a.startswith("hl.dsp.window.resize"):
        return "Resize a window with the mouse"
    if a.startswith("hl.dsp.layout") and "togglesplit" in a:
        return "Turn the split (side by side / stacked)"
    if a.startswith("hl.dsp.workspace.toggle_special"):
        return "Show / hide the scratchpad"
    if a.startswith("hl.dsp.window.move") and wsv:
        if wsv.startswith("special"):
            return "Move the window to the scratchpad"
        return f"Move the window to workspace {wsv}"
    if a.startswith("hl.dsp.focus"):
        d = re.search(r'direction\s*=\s*"(\w+)"', a)
        if d:
            return f"Focus the window {'to the ' if d.group(1) in ('left', 'right') else ''}{d.group(1)}".replace(
                "window up", "window above").replace("window down", "window below")
        if wsv == "e+1":
            return "Next workspace"
        if wsv == "e-1":
            return "Previous workspace"
        if wsv:
            return f"Go to workspace {wsv}"
    return ""


def scan(paths):
    """{normalised combo: description} for every hl.bind in these Lua files (loops over workspaces
    are expanded: the key is the digit, the workspace its number)."""
    out = {}
    for p in paths:
        try:
            lines = Path(p).read_text(errors="replace").splitlines()
        except OSError:
            continue
        env = {"mainMod": "SUPER"}
        loop = None
        for line in lines:
            code = strip_comment(line)
            lm = _LOCAL.match(code)
            if lm:
                env[lm.group(1)] = lm.group(2)
                continue
            fm = _LOOP.match(code)
            if fm:
                loop = fm.group(1)
                continue
            if loop and re.match(r"^\s*end\b", code):
                loop = None
                continue
            bm = _BIND.search(code)
            if not bm:
                continue
            combo_expr, action = bm.group(1), bm.group(2)
            desc = describe_action(action.strip(), env, loop)
            if not desc:
                continue
            combo = _expand(combo_expr, env)
            if loop and "{key}" in combo or (loop and "{" in combo):
                for n in range(1, 11):
                    key = str(n % 10)
                    c = re.sub(r"\{[^}]*\}", key, combo)
                    out.setdefault(norm(c), desc.replace("{n}", str(n)))
            elif "{" not in combo:
                out.setdefault(norm(combo), desc)
    return out


def default_paths():
    home = Path.home()
    paths = sorted((home / ".config/hypr").glob("*.lua"))
    paths += sorted(Path("/usr/share/arclight/hypr").glob("*.lua"))
    return paths


def names():
    return scan(default_paths())
