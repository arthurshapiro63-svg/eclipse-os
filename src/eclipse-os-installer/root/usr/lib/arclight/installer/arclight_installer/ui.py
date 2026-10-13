"""Terminal UI helpers: gum when available (styled), plain prompts otherwise."""
import os
import shutil
import subprocess
import sys

# the Eclipse palette (Arthur's photo: SF90 under the eclipse at dusk): the sun's gold, warm text, a rare red
GOLD = "#FFC94A"
BLUE = GOLD  # old name, kept for callers; the accent is the sun now
BRIGHT = "#FFF6E4"
TEXT = "#ECEAE6"
MUTED = "#9A958E"
RED = "#D42B2B"
WARN = "#E0B040"
OK = "#3FD69A"
GUM = shutil.which("gum") and sys.stdin.isatty()


def _gum(args, input=None):
    p = subprocess.run(["gum"] + args, stdout=subprocess.PIPE, input=input, text=True)
    if p.returncode == 130:
        raise KeyboardInterrupt
    return p.returncode, p.stdout.rstrip("\n")


def os_name():
    try:
        from arclight import identity
        return identity.os_name()
    except Exception:
        return "Eclipse OS"


def logo():
    # a total eclipse: white corona ring, black moon, blue rays
    b, c, w, m, r = ("\033[38;2;91;134;200m", "\033[1;38;2;242;245;255m", "\033[1;38;2;233;237;245m",
                     "\033[38;2;138;151;174m", "\033[0m")
    print(f"""
{b}          ╲   │   ╱
{b}       ·   {c}▄▀▀▀▀▀▄{b}   ·
{b}     ───  {c}█       █{b}  ───      {w}{os_name()}{r}
{b}       ·   {c}▀▄▄▄▄▄▀{b}   ·        {m}AI-native Arch · installer{r}
{b}          ╱   │   ╲{r}
""")


def header(title, sub=None):
    if GUM:
        args = ["style", "--foreground", TEXT, "--border", "rounded", "--border-foreground", GOLD, "--padding", "0 2",
                "--bold", title]
        if sub:
            args += ["", sub]
        subprocess.run(["gum"] + args)
    else:
        print(f"\n== {title} ==")
        if sub:
            print(sub)


def say(text, color=None):
    if GUM:
        subprocess.run(["gum", "style", "--foreground", color or TEXT, text])
    else:
        print(text)


def note(text):
    say(text, MUTED)


def choose(prompt, options, default=None):
    """options: list of (key, label). Returns key."""
    labels = [l for _, l in options]
    if GUM:
        args = ["choose", "--header", prompt, "--cursor.foreground", GOLD, "--selected.foreground", BRIGHT,
                "--header.foreground", TEXT]
        if default is not None:
            for k, l in options:
                if k == default:
                    args += ["--selected", l]
        rc, out = _gum(args + labels)
        if rc != 0 or not out:
            raise KeyboardInterrupt
        return next(k for k, l in options if l == out)
    print(prompt)
    for i, (_, l) in enumerate(options, 1):
        print(f"  {i}) {l}")
    while True:
        a = input("> ").strip()
        if not a and default is not None:
            return default
        if a.isdigit() and 1 <= int(a) <= len(options):
            return options[int(a) - 1][0]


def choose_many(prompt, options, selected=()):
    labels = [l for _, l in options]
    if GUM:
        args = ["choose", "--no-limit", "--header", prompt, "--cursor.foreground", GOLD, "--selected.foreground", BRIGHT]
        for k, l in options:
            if k in selected:
                args += ["--selected", l]
        rc, out = _gum(args + labels)
        chosen = set(out.splitlines()) if rc == 0 else set()
        return [k for k, l in options if l in chosen]
    print(prompt + " (numbers separated by spaces, empty = keep)")
    for i, (k, l) in enumerate(options, 1):
        print(f"  {i}) [{'x' if k in selected else ' '}] {l}")
    a = input("> ").strip()
    if not a:
        return list(selected)
    return [options[int(x) - 1][0] for x in a.split() if x.isdigit() and 1 <= int(x) <= len(options)]


def ask(prompt, default="", password=False, validate=None, hint=None):
    while True:
        if GUM:
            args = ["input", "--header", prompt, "--value", default, "--cursor.foreground", GOLD,
                    "--header.foreground", TEXT, "--width", "60"]
            if password:
                args += ["--password", "--value", ""]
            if hint:
                args += ["--placeholder", hint]
            rc, out = _gum(args)
            if rc != 0:
                raise KeyboardInterrupt
        else:
            import getpass
            out = getpass.getpass(prompt + " ") if password else (input(f"{prompt} [{default}] ") or default)
        out = out.strip() if not password else out
        if validate:
            err = validate(out)
            if err:
                say(f"  {err}", RED)
                continue
        return out


def confirm(prompt, default=True):
    if GUM:
        args = ["confirm", prompt, "--prompt.foreground", TEXT, "--selected.background", GOLD, "--selected.foreground", "#1A1205"]
        if not default:
            args.append("--default=false")
        rc = subprocess.run(["gum"] + args).returncode
        if rc == 130:
            raise KeyboardInterrupt
        return rc == 0
    a = input(f"{prompt} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not a else a.startswith("y")


def spin(title, fn):
    """Run fn() with a spinner (in-process: just print the title then run)."""
    say(f"… {title}", MUTED)
    return fn()


class Progress:
    def __init__(self):
        self.last = None

    def progress(self, msg):
        if msg.startswith("▸"):
            say(msg, BRIGHT)
        elif msg.startswith("✓"):
            say(msg, OK)
        elif msg.startswith("✗"):
            say(msg, RED)
        else:
            print(f"   {msg}", flush=True)
