"""Headless timed run in the terminal:  eclipse-ai --work-for 45m "goal here"   (from Arch AI by Arthur)

Prints the model's text as it streams, keeps a live status line at the bottom, and
stops cleanly on q, Esc or Ctrl+C. Also: --root-queue (show the root review script),
--clear-root-queue, --run-root-queue (run it as one root batch through arclightd), --runs.
"""
import os
import signal
import subprocess
import sys
import threading
import time

from . import config, elevate, rootq, tools
from .autonomous import RUNS_DIR, Run, fmt, parse_duration
from .ollama_client import Ollama

USAGE = """usage: eclipse-ai                                    open the window
       eclipse-ai --send TEXT                        open the window and send TEXT
       eclipse-ai --work-for DURATION GOAL...        timed autonomous run in this terminal
       eclipse-ai --work-for DURATION --gui GOAL...  same, but inside the Eclipse AI window
       eclipse-ai --root-queue                       show commands waiting for you (need root)
       eclipse-ai --clear-root-queue                 delete that script
       eclipse-ai --run-root-queue                   run the plain sudo lines in it as root (no password)
       eclipse-ai --runs                             list past runs
DURATION: 10m, 45m, 1h, 1h30m, 3h.   Stop a run with q, Esc or Ctrl+C."""


class Term:
    """Streams text and redraws one status line at the bottom (only when stdout is a terminal)."""

    def __init__(self):
        self.tty = sys.stdout.isatty()
        self.lock = threading.Lock()
        self.status = ""
        self.at_line_start = True
        self.last_plain = 0.0

    def _clear_status(self):
        if self.tty and self.status:
            sys.stdout.write("\r\x1b[2K")

    def _draw_status(self):
        if self.tty and self.status:
            if not self.at_line_start:
                sys.stdout.write("\n"); self.at_line_start = True
            sys.stdout.write("\x1b[2m" + self.status[:os.get_terminal_size().columns - 1] + "\x1b[0m")
            sys.stdout.flush()

    def write(self, text: str):
        if not text:
            return
        with self.lock:
            self._clear_status()
            if self.at_line_start and self.tty and self.status:
                pass
            sys.stdout.write(text)
            self.at_line_start = text.endswith("\n")
            if not self.at_line_start and self.tty and self.status:
                sys.stdout.write("\n"); self.at_line_start = True
            self._draw_status()
            sys.stdout.flush()

    def line(self, text: str):
        self.write(text.rstrip("\n") + "\n")

    def set_status(self, text: str):
        with self.lock:
            self.status = text
            if self.tty:
                if not self.at_line_start:
                    sys.stdout.write("\n"); self.at_line_start = True
                sys.stdout.write("\r\x1b[2K")
                self._draw_status()
            elif time.time() - self.last_plain > 30:
                self.last_plain = time.time()
                sys.stdout.write(f"[{text}]\n"); sys.stdout.flush()

    def end(self):
        with self.lock:
            self._clear_status(); self.status = ""
            if not self.at_line_start:
                sys.stdout.write("\n")
            sys.stdout.flush()


class TermUI:
    """What autonomous.Run needs, drawn in the terminal."""

    def __init__(self, term: Term):
        self.term = term

    def on_text(self, delta):
        self.term.write(delta)

    def on_tool_start(self, name, shown, args):
        self.term.line(f"\x1b[34m▶ {shown}\x1b[0m" if self.term.tty else f"▶ {shown}")
        return {"out": ""}

    def on_tool_done(self, card, delta, result):
        if delta is not None:
            card["out"] += delta
            return
        if result is not None:
            mark = "⏸" if result.queued else ("✔" if result.ok else "✖")
            shown = card["out"] if card["out"] else result.text
            shown = shown.strip()
            if len(shown) > 700:
                shown = shown[:400] + "\n…\n" + shown[-250:]
            self.term.line("  " + shown.replace("\n", "\n  ") if shown else "")
            self.term.line(f"  {mark}")

    def on_status(self, text):
        pass  # the run status line covers it

    def on_note(self, text):
        self.term.line(f"\x1b[2m{text}\x1b[0m" if self.term.tty else text)

    def on_run_status(self, st):
        self.term.set_status(f"⏱ {fmt(st['elapsed'])} elapsed · {fmt(st['remaining'])} left · step {st['step']} · {st['last']}")


def _keys(run: Run, stop_event: threading.Event):
    """Single-key stop: q, Esc or Ctrl+C. Restores the terminal afterwards."""
    if not sys.stdin.isatty():
        return
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        import select
        while not stop_event.is_set():
            if select.select([fd], [], [], 0.2)[0]:
                ch = os.read(fd, 1)
                if ch in (b"q", b"Q", b"\x1b", b"\x03"):
                    run.stop(); return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def ensure_server(cfg: dict) -> bool:
    """Start the model server unit if needed. Returns True if we started it (so we stop it after)."""
    client = Ollama(cfg["host"])
    if client.is_up():
        return False
    subprocess.run(["systemctl", "--user", "--no-ask-password", "start", config.OLLAMA_UNIT], capture_output=True, timeout=30)
    for _ in range(60):
        if client.is_up():
            return True
        time.sleep(0.5)
    return True


def _root_ctx() -> tools.ToolContext:
    """The flag itself is the consent (there is no card in a terminal); output streams to stdout."""
    ctx = tools.ToolContext(approve=lambda a: (setattr(a, "approved", True), a)[1],
                            on_output=lambda s: (sys.stdout.write(s), sys.stdout.flush()))
    ctx.note = lambda t: print(t)
    return ctx


def root_cmd(argv: list[str]) -> int:
    config.ensure_dirs()
    if not elevate.available():
        print("eclipse-ai: the Eclipse root service (arclightd) is not running (arc doctor says how to fix it).",
              file=sys.stderr)
        return 1
    ctx = _root_ctx()
    cmds, rest = elevate.queue_split()
    if cmds:
        print(f"Running {len(cmds)} root command{'s' if len(cmds) != 1 else ''} from {rootq.SCRIPT} (no password):")
        for c in cmds:
            print(f"  {c}")
    r = elevate.run_queue(ctx, confirm=False)
    print("\n" + r.text)
    return 0 if r.ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not config.ai_enabled():
        print("AI features are turned off. Turn them on in Settings -> AI.", file=sys.stderr)
        return 3
    if "--run-root-queue" in argv:
        return root_cmd(argv)
    if "--root-queue" in argv:
        print(rootq.SCRIPT.read_text() if rootq.SCRIPT.exists() else f"nothing waiting ({rootq.SCRIPT} does not exist)")
        return 0
    if "--clear-root-queue" in argv:
        rootq.clear(); print(f"removed {rootq.SCRIPT}"); return 0
    if "--runs" in argv:
        for d in sorted(RUNS_DIR.glob("*"))[-20:]:
            goal = (d / "goal.md").read_text().strip().splitlines()[0] if (d / "goal.md").exists() else "?"
            print(f"{d.name}  {goal[:70]}")
        return 0
    if "--work-for" not in argv:
        print(USAGE); return 2
    i = argv.index("--work-for")
    try:
        seconds = parse_duration(argv[i + 1])
    except (IndexError, ValueError) as e:
        print(f"eclipse-ai: {e}\n{USAGE}", file=sys.stderr); return 2
    rest = [a for a in argv[:i] + argv[i + 2:] if a != "--gui"]
    goal = " ".join(rest).strip()
    if not goal:
        print("eclipse-ai: give the goal after the duration, e.g.  eclipse-ai --work-for 30m \"make ~/Projects/x build\"", file=sys.stderr)
        return 2

    config.ensure_dirs()
    cfg = config.load()
    term = Term()
    ui = TermUI(term)
    term.line(f"Eclipse AI · timed run · {fmt(seconds)} · {config.display_name(cfg, cfg['model'])}")
    term.line(f"goal: {goal}")
    term.line("stop any time with q, Esc or Ctrl+C\n")
    started_server = ensure_server(cfg)
    if not Ollama(cfg["host"]).is_up():
        term.line(f"⚠ model server not reachable (systemctl --user status {config.OLLAMA_UNIT})"); return 1
    run = Run(cfg, goal, seconds, ui)
    stop_event = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: run.stop())
    threading.Thread(target=_keys, args=(run, stop_event), daemon=True).start()
    try:
        report = run.start()
    finally:
        stop_event.set()
        term.end()
        if started_server:
            subprocess.run(["systemctl", "--user", "--no-ask-password", "stop", config.OLLAMA_UNIT], capture_output=True, timeout=30)
    print("\n" + run.summary_for_chat())
    if elevate.queue_split()[0]:
        print("Run the plain sudo lines as root (no password):  eclipse-ai --run-root-queue")
    return 0 if run.outcome in ("finished", "timeout") else 1
