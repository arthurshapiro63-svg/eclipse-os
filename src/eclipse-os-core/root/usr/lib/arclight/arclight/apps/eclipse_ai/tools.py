"""Tools the model can call. Each returns a short text result for the model.
(From Arch AI by Arthur; the Eclipse OS edition.)

Every action goes through `ctx.approve()` unless safety.py says it is read-only.
Root: in chat with root_mode "ask" (the default) a plain `sudo …` (or `arc root …`) command shows an
approval card with the exact command; after a yes it runs as root through arclightd, with no password
(elevate.py). Timed runs, root_mode "queue" and mixed commands append it to the root review script
(rootq.py) instead, reported back as "not run". Packages go through arclightd's package service, which
makes a restore point first (btrfs installs). A terminal sudo prompt is never possible: sudo reaching
`_run_shell` becomes `sudo -n`. Every command and its output is written to the log. No command can wait
for input: stdin is /dev/null, sudo/git/ssh/pacman are forced non-interactive, and every command has a
deadline; a stuck one is killed with its whole process group.
"""
import json
import os
import re
import platform
import selectors
import shlex
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import config, elevate, rootq, safety, store, sysapi

MAX_OUT = 6000  # chars returned to the model (full output goes to the log)


@dataclass
class Approval:
    """What the UI shows before a risky action runs."""
    title: str            # e.g. "Run command"
    command: str          # exact command / operation shown to the user
    reasons: list[str]    # why we ask
    preview: str = ""     # optional file preview
    approved: bool = False
    heading: str = ""     # card title as is (default: "<title> — may I?")
    yes: str = "Yes, run it"
    no: str = "No"
    root: bool = False    # runs as root (through arclightd) after a yes


@dataclass
class ToolResult:
    text: str
    ok: bool = True
    queued: bool = False  # not run: waiting in the root review script
    codes: list | None = None     # root batch: exit code per command (None = did not run)
    still_running: bool = False   # root batch still running after Stop / limit (cannot be killed)


TOOLS = [
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a bash command on this Eclipse OS (Arch Linux) machine and return its output. Read-only commands run right away; risky ones ask the user first. Prefer user-level ways (inside ~, systemctl --user, ~/.local/bin). If root is truly needed, start the command with plain `sudo` (every part: no `cd x && sudo …`, no `sudo -u`, never with yay/paru): the user sees it, clicks yes, and it runs as root (no password). In timed runs it is queued for the user instead.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "The exact bash command to run."},
        }, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file (supports ~). Returns the content with line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or fully overwrite a text file. Overwriting asks the user first. Prefer edit_file for small changes. Files outside ~ (like /etc) are written as root after the user clicks yes (queued for the user in timed runs).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"},
        }, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace an exact text snippet in a file with new text (the user is asked first). 'find' must match exactly once. Use this for config files like hyprland.lua or the terminal config. Files outside ~ are written as root after the user clicks yes.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"},
        }, "required": ["path", "find", "replace"]}}},
    {"type": "function", "function": {
        "name": "install_packages",
        "description": "Install packages (official repos and the AUR) through Eclipse's package service. A restore point is made first. The user clicks yes in the window; no password.",
        "parameters": {"type": "object", "properties": {
            "packages": {"type": "array", "items": {"type": "string"}},
        }, "required": ["packages"]}}},
    {"type": "function", "function": {
        "name": "remove_packages",
        "description": "Remove packages (with their unneeded dependencies) through Eclipse's package service, after the user clicks yes. Queued for the user in timed runs.",
        "parameters": {"type": "object", "properties": {
            "packages": {"type": "array", "items": {"type": "string"}},
        }, "required": ["packages"]}}},
    {"type": "function", "function": {
        "name": "update_system",
        "description": "List pending package updates, then update the whole system (repos and AUR) through Eclipse's package service after the user clicks yes. A restore point is made first. In timed runs the update is queued instead.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "open_app",
        "description": "Open a desktop app, a file or a URL (e.g. 'files', 'terminal', 'browser', 'steam', '~/Pictures', 'https://archlinux.org').",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string"},
        }, "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "system_info",
        "description": "Get a summary of this machine: OS, kernel, CPU, GPU, memory, disk, uptime, desktop, config file locations.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "find_settings",
        "description": "Search Eclipse OS settings (look, wallpaper, gaps, blur, keyboard, mouse, sound, screens, power, night light, AI, ...). Returns setting keys with their current values. Use this before change_setting.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words to search for, e.g. 'gaps', 'wallpaper', 'volume'."},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "change_setting",
        "description": "Change one Eclipse OS setting by its key (from find_settings). It applies at once and is kept. The user clicks yes first.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"}, "value": {"type": "string", "description": "The new value (true/false, a number or text)."},
        }, "required": ["key", "value"]}}},
]

# Only offered during a timed autonomous run.
AUTONOMOUS_TOOLS = [
    {"type": "function", "function": {
        "name": "update_plan",
        "description": "Replace the run's plan (a short numbered list of remaining steps). Call it when the plan changes or a step is done.",
        "parameters": {"type": "object", "properties": {
            "plan": {"type": "string"},
        }, "required": ["plan"]}}},
    {"type": "function", "function": {
        "name": "log_progress",
        "description": "Record one line in the run notes so future steps remember it: what was tried and whether it worked or failed.",
        "parameters": {"type": "object", "properties": {
            "outcome": {"type": "string", "enum": ["worked", "failed", "tried", "learned"]},
            "text": {"type": "string"},
        }, "required": ["outcome", "text"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Stop the run early because the goal is done (or impossible). Only call it after you verified the result with a command.",
        "parameters": {"type": "object", "properties": {
            "completed": {"type": "string", "description": "What is done."},
            "verified": {"type": "string", "description": "How you checked it (the command and what it showed)."},
            "still_broken": {"type": "string", "description": "What is not done or not working, or 'nothing'."},
        }, "required": ["completed", "verified", "still_broken"]}}},
]


def _trim(text: str, limit: int = MAX_OUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... [{len(text) - limit} chars cut, full output is in the log] ...\n" + text[-half:]


class ToolContext:
    """Bridges tools and the UI. `approve` blocks the worker thread until the user answers."""

    def __init__(self, approve, on_output=None):
        self.approve = approve                # Approval -> Approval (with .approved filled)
        self.on_output = on_output or (lambda s: None)
        self.note = lambda text: None         # one-line status shown in the chat (allowed / declined / queued)
        self.cancelled = False
        self.deadline: float | None = None    # epoch seconds; no command may run past it
        cfg = config.load()
        self.command_timeout: float = float(cfg.get("command_timeout", 120))
        self.root_mode: str = str(cfg.get("root_mode", "ask"))   # "ask": arclightd after a yes · "queue": root review script only
        self.max_out = MAX_OUT
        self.run = None                       # autonomous.Run while a timed run is active
        self.autonomous = False               # True: nobody is watching, auto-approve (except hard blocks)

    def time_left(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.time()


class StopRun(Exception):
    """Raised by the `finish` tool to end an autonomous run early."""


# ---------- shell ----------
NONINTERACTIVE_ENV = {
    "PAGER": "cat", "GIT_PAGER": "cat", "SYSTEMD_PAGER": "cat", "MANPAGER": "cat", "LESS": "-FRX",
    "SYSTEMD_COLORS": "0", "NO_COLOR": "1", "TERM": "dumb", "DEBIAN_FRONTEND": "noninteractive",
    "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", "SSH_ASKPASS": "/bin/false",
    "SSH_ASKPASS_REQUIRE": "force", "SUDO_ASKPASS": "/bin/false", "PIP_NO_INPUT": "1",
    "npm_config_yes": "true", "HOMEBREW_NO_AUTO_UPDATE": "1", "SYSTEMD_ASK_PASSWORD": "0",
}


def harden(command: str) -> str:
    """Make sure a command can never wait for a password or a keypress."""
    # belt and braces: sudo/doas that somehow reaches here fail instantly instead of prompting
    command = re.sub(r"(^|[\s;&|(])sudo(\s)", r"\1sudo -n\2", command)
    command = re.sub(r"(^|[\s;&|(])(yay|paru)(\s)", r"\1\2 --noconfirm --sudoflags=-n\3", command)
    command = re.sub(r"(^|[\s;&|(])pacman\s+(-\w*[SRU]\w*)(?![^|;&]*--noconfirm)", r"\1pacman \2 --noconfirm", command)
    command = re.sub(r"(^|[\s;&|(])systemctl(\s)(?![^|;&]*--no-ask-password)", r"\1systemctl --no-ask-password\2", command)
    command = re.sub(r"(^|[\s;&|(])ssh(\s)(?![^|;&]*BatchMode)", r"\1ssh -o BatchMode=yes\2", command)
    return command


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the command and everything it started (it runs in its own session)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        except Exception:
            pass
        try:
            proc.wait(timeout=1.5)
            return
        except subprocess.TimeoutExpired:
            continue


def _run_shell(command: str, ctx: ToolContext, kind: str = "shell", timeout: float | None = None) -> ToolResult:
    env = dict(os.environ)
    env.update(NONINTERACTIVE_ENV)
    command = harden(command)
    limit = timeout or ctx.command_timeout
    left = ctx.time_left()
    if left is not None:
        limit = max(3.0, min(limit, left))
    out_parts: list[str] = []
    rc: int | None = None
    proc = None
    try:
        proc = subprocess.Popen(["bash", "-c", command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env, cwd=str(Path.home()),
                                start_new_session=True, text=True, errors="replace")
        deadline = time.time() + limit
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        killed = False
        while True:
            if ctx.cancelled:
                _kill_group(proc); out_parts.append("\n[cancelled by user]"); killed = True; break
            if time.time() > deadline:
                _kill_group(proc); out_parts.append(f"\n[timed out after {int(limit)}s and was killed]"); killed = True; break
            if sel.select(timeout=0.2):
                line = proc.stdout.readline()
                if not line:
                    break
                out_parts.append(line)
                ctx.on_output(line)
        if not killed:
            rest = proc.stdout.read()
            if rest:
                out_parts.append(rest); ctx.on_output(rest)
            rc = proc.wait(timeout=10)
        else:
            rc = proc.poll()
    except Exception as e:
        out_parts.append(f"\n[error: {e}]")
        if proc is not None:
            _kill_group(proc)
    output = "".join(out_parts)
    store.log_command(command, rc, output, kind)
    text = output.strip() or "(no output)"
    if "sudo: a password is required" in text or "sudo: a terminal is required" in text:
        text += "\n(sudo cannot ask for a password here; start the command with plain sudo in run_command so it runs as root after the user's yes)"
    return ToolResult(f"exit code: {rc}\n{_trim(text, ctx.max_out)}", ok=(rc == 0))


# ---------- approval ----------
def ask(ctx: ToolContext, approval: Approval) -> None:
    """Interactive: show the approval card. Autonomous: auto-approve unless hard-blocked.
    Raises PermissionError when the action may not run."""
    why = safety.hard_block(approval.command)
    if why:
        ctx.note(f"✖ refused ({why}): {approval.command}")
        raise PermissionError(f"refused, {why}. This is never run unattended.")
    if ctx.autonomous:
        ctx.note(f"✔ auto-approved (timed run): {approval.command}")
        return
    if not ctx.approve(approval).approved:
        ctx.note(f"✖ declined: {approval.command}")
        raise PermissionError("The user said no.")
    ctx.note(f"✔ allowed: {approval.command}")


def queue_root(ctx: ToolContext, command: str, why: str, reason: str = "") -> ToolResult:
    """Not run now: append to the root review script and tell the model."""
    run_id = getattr(ctx.run, "id", "") if ctx.run else ""
    reason = reason or ("timed runs never run root commands (nobody is watching)" if ctx.autonomous else
                        "root_mode is \"queue\", so root commands are not run" if ctx.root_mode == "queue" else "")
    line, added = rootq.add(command, f"{why}: {reason}" if reason else why, run_id)
    ctx.note(f"⏸ needs root, queued for your review: {command}")
    store.log_command(command, None, f"queued in {rootq.SCRIPT} line {line}" + (f" ({reason})" if reason else ""), "root-queue")
    state = "queued" if added else "was already queued"
    return ToolResult(
        f"NOT RUN: this needs root" + (f" and {reason}" if reason else "") + f". The command {state} in "
        f"{rootq.SCRIPT} (line {line}) for the user to review and run. Do not retry it unchanged. "
        "Use a user-level way if one exists (inside ~, ~/.local/bin, systemctl --user), or install_packages for packages; "
        "otherwise carry on with the rest and tell the user the script is waiting.", ok=False, queued=True)




def use_root(ctx: ToolContext) -> bool:
    """Root runs right away (after a yes): chat only (never a timed run), root_mode "ask"."""
    return not ctx.autonomous and ctx.root_mode != "queue"


def root_command(ctx: ToolContext, command: str, why: str, title: str = "Run as root", preview: str = "",
                 timeout: float | None = None) -> ToolResult:
    """A command that needs root: approval card with the exact command, then arclightd runs it (no password).
    Queued instead in a timed run, with root_mode "queue", for mixed commands, or when arclightd is down."""
    command = safety.normalize_root(command)
    blocked = safety.hard_block(command)
    if blocked:
        ctx.note(f"✖ refused ({blocked}): {command}")
        raise PermissionError(f"refused, {blocked}. This is never run.")
    if not use_root(ctx):
        return queue_root(ctx, command, why)
    reason = elevate.check(command)
    if reason:
        return queue_root(ctx, command, why, reason)
    if not elevate.available():
        return queue_root(ctx, command, why, "the Eclipse root service (arclightd) is not running")
    ask(ctx, Approval(title, elevate.strip_sudo(command), ["runs as root", "no password needed"],
                      preview=preview, heading=f"{title}?", yes="Yes, run as root", root=True))
    return elevate.run_as_root([command], ctx, why=why, timeout=timeout)


# ---------- tools ----------
def run_command(args: dict, ctx: ToolContext) -> ToolResult:
    command = str(args.get("command", "")).strip()
    if not command:
        return ToolResult("error: empty command", ok=False)
    if safety.needs_root(command):
        return root_command(ctx, command, "run_command")
    auto, reasons = safety.classify(command)
    if not auto:
        ask(ctx, Approval("Run command", command, reasons))
    return _run_shell(command, ctx)


def read_file(args: dict, ctx: ToolContext) -> ToolResult:
    p = safety.expand(str(args.get("path", "")))
    try:
        text = p.read_text(errors="replace")
    except Exception as e:
        store.log_command(f"read {p}", 1, str(e), "file")
        return ToolResult(f"error: {e}", ok=False)
    store.log_command(f"read {p}", 0, f"{len(text)} chars", "file")
    lines = text.splitlines()
    numbered = "\n".join(f"{i+1:4d}| {l}" for i, l in enumerate(lines))
    return ToolResult(f"{p} ({len(lines)} lines)\n{_trim(numbered, min(12000, ctx.max_out * 2))}")


STAGE = config.DATA_DIR / "root-stage"
BAK = config.BACKUP_SUFFIX


def _write(p: Path, content: str, ctx: ToolContext, title: str, preview: str) -> ToolResult:
    auto, reasons = safety.classify_write(str(p))
    outside = any(r.startswith("touches") or r.startswith("outside") for r in reasons)
    if outside:
        # Stage the content in ~, then copy it as root (after a yes), or queue it.
        STAGE.mkdir(parents=True, exist_ok=True)
        staged = STAGE / (str(p).strip("/").replace("/", "__") + f".{int(time.time())}")
        staged.write_text(content)
        q = shlex.quote
        existed = p.exists()
        if existed:   # back up, then copy over it (cp onto an existing file keeps its owner and mode)
            cmd = f"sudo cp -a {q(str(p))} {q(str(p) + BAK)} && sudo cp {q(str(staged))} {q(str(p))}"
        else:
            cmd = f"sudo install -D -m 644 {q(str(staged))} {q(str(p))}"
        r = root_command(ctx, cmd, f"{title.lower()} outside home", title=f"{title} as root", preview=preview)
        if r.ok:
            store.log_command(f"write {p}", 0, f"{len(content)} chars written as root" + (f" (backup: *{BAK})" if existed else ""), "file")
            r.text = f"wrote {p} as root ({len(content.splitlines())} lines)." + (f" Backup kept as {p.name}{BAK}." if existed else "")
        elif r.queued:
            r.text = f"NOT WRITTEN: {p} is outside your home folder. The new content is staged at {staged} and the copy is queued in {rootq.SCRIPT}. Do not retry.\n{r.text}"
        return r
    if not auto:
        ask(ctx, Approval(title, f"write {p}", reasons, preview=preview))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        if existed:
            shutil.copy2(p, p.with_name(p.name + BAK))
        p.write_text(content)
    except Exception as e:
        store.log_command(f"write {p}", 1, str(e), "file")
        return ToolResult(f"error: {e}", ok=False)
    store.log_command(f"write {p}", 0, f"{len(content)} chars written" + (f" (backup: *{BAK})" if existed else ""), "file")
    return ToolResult(f"wrote {p} ({len(content.splitlines())} lines)." + (f" Backup kept as {p.name}{BAK}." if existed else ""))


def write_file(args: dict, ctx: ToolContext) -> ToolResult:
    p = safety.expand(str(args.get("path", "")))
    content = str(args.get("content", ""))
    return _write(p, content, ctx, "Write file", _trim(content, 1500))


def edit_file(args: dict, ctx: ToolContext) -> ToolResult:
    p = safety.expand(str(args.get("path", "")))
    find, replace = str(args.get("find", "")), str(args.get("replace", ""))
    try:
        text = p.read_text()
    except Exception as e:
        return ToolResult(f"error: {e}", ok=False)
    n = text.count(find)
    if not find or n == 0:
        return ToolResult("error: the 'find' text was not found in the file. Read the file and copy the exact text.", ok=False)
    if n > 1:
        return ToolResult(f"error: the 'find' text appears {n} times. Include more surrounding lines so it is unique.", ok=False)
    preview = f"--- remove\n{find}\n+++ add\n{replace}"
    return _write(p, text.replace(find, replace, 1), ctx, "Edit file", _trim(preview, 1500))


# ---------- packages: Eclipse's package service (arclightd pkg.*), a restore point first ----------
def _pk(packages: list[str]) -> str:
    return " ".join(shlex.quote(x) for x in packages)


def _pkgs(args: dict) -> list[str]:
    return [str(x).strip() for x in args.get("packages", []) if str(x).strip()]


def pkg_job(method: str, params: dict, on_line, cancelled=lambda: False) -> dict:
    """Run one arclightd package job (pkg.install / pkg.remove / pkg.upgrade); every output line goes to
    on_line as it happens (pkg.status). Returns {"result", "snapshot"}; raises on failure. A package job
    is never killed half-way (that would break pacman); Stop only stops following it."""
    stream = {"ok": True, "job": None, "next": 0, "snapshot": None, "mine": None}
    try:
        stream["job"] = sysapi.call("pkg.status")["job"]          # the job id before ours
    except Exception:
        stream["ok"] = False
    box: dict = {}

    def main():
        try:
            box["result"] = sysapi.call(method, **params)
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=main, daemon=True)
    t.start()

    def poll():
        mine = stream["mine"]
        try:
            st = sysapi.call("pkg.status", since=stream["next"] if mine else 0, job=mine if mine else -1)
        except Exception:
            stream["ok"] = False
            return
        if st["job"] == stream["job"] or (mine and st["job"] != mine):
            return
        stream["mine"], stream["next"] = st["job"], st["next"]
        stream["snapshot"] = st.get("snapshot") or stream["snapshot"]
        for line in st.get("lines") or []:
            on_line(line + "\n")

    while t.is_alive():
        t.join(0.4)
        if cancelled():
            raise TimeoutError("stopped following it; the package job keeps running and finishes by itself")
        if stream["ok"]:
            poll()
    if stream["ok"]:
        poll()
    if "error" in box:
        e = box["error"]
        raise RuntimeError(getattr(e, "message", None) or str(e))
    res = box.get("result")
    snap = (res or {}).get("snapshot") if isinstance(res, dict) else None
    return {"result": res, "snapshot": snap or stream["snapshot"]}


def _snap_text(snap) -> str:
    if not snap:
        return ""
    sid = snap.get("id") if isinstance(snap, dict) else snap
    return f" A restore point was made first ({sid})."


def _pkg_root(ctx: ToolContext, title: str, shown: str, reasons: list[str], method: str, params: dict,
              queued_cmd: str, why: str, queue_in_runs: bool) -> ToolResult:
    """Package work through arclightd: card first (auto-approved in a timed run unless queue_in_runs)."""
    if ctx.root_mode == "queue" or (ctx.autonomous and queue_in_runs):
        return queue_root(ctx, queued_cmd, why)
    if not elevate.available():
        return queue_root(ctx, queued_cmd, why, "the Eclipse package service (arclightd) is not running")
    ask(ctx, Approval(title, shown, reasons, heading=f"{title}?", yes="Yes, do it", root=True))
    ctx.on_output("working through Eclipse's package service (no password)…\n")
    try:
        r = pkg_job(method, params, ctx.on_output, lambda: ctx.cancelled)
    except TimeoutError as e:
        return ToolResult(f"{e}.", ok=False, still_running=True)
    except Exception as e:
        store.log_command(shown, 1, str(e), "pkg")
        return ToolResult(f"failed: {_trim(str(e), 3000)}", ok=False)
    res = r["result"] or {}
    out = json.dumps(res, indent=1)[:4000] if isinstance(res, (dict, list)) else str(res)
    if isinstance(res, dict) and res.get("status") in ("partial", "failed"):   # never report this as done
        store.log_command(shown, 1, out, "pkg")
        return ToolResult(f"NOT finished ({res['status']}): {shown}. Updated: {', '.join(res.get('updated') or []) or 'nothing'}. "
                          f"Not updated: {', '.join(res.get('failed') or [])}.{_snap_text(r['snapshot'])}\n"
                          f"{_trim(res.get('diagnostics') or '', 1500)}", ok=False)
    store.log_command(shown, 0, out, "pkg")
    return ToolResult(f"done: {shown}.{_snap_text(r['snapshot'])}\n{_trim(out, 2000)}")


def _installed(p: str) -> bool:
    try:
        return subprocess.run(["pacman", "-Q", p], capture_output=True, timeout=10, stdin=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False


def install_packages(args: dict, ctx: ToolContext) -> ToolResult:
    pkgs = _pkgs(args)
    if not pkgs:
        return ToolResult("error: no packages given", ok=False)
    already = [p for p in pkgs if _installed(p)]
    todo = [p for p in pkgs if p not in already]
    if not todo:
        return ToolResult(f"already installed: {', '.join(already)}")
    r = _pkg_root(ctx, "Install packages", f"install {' '.join(todo)}",
                  ["installs software for the whole system", "a restore point is made first", "no password needed"],
                  "pkg.install", {"names": todo, "aur": True}, f"sudo pacman -S --needed --noconfirm {_pk(todo)}",
                  "install_packages", queue_in_runs=False)
    if already:
        r.text = f"already installed: {', '.join(already)}\n" + r.text
    return r


def remove_packages(args: dict, ctx: ToolContext) -> ToolResult:
    pkgs = _pkgs(args)
    if not pkgs:
        return ToolResult("error: no packages given", ok=False)
    return _pkg_root(ctx, "Remove packages", f"remove {' '.join(pkgs)}",
                     ["removes software (and what only it needed)", "a restore point is made first", "no password needed"],
                     "pkg.remove", {"names": pkgs}, f"sudo pacman -Rns --noconfirm {_pk(pkgs)}", "remove_packages",
                     queue_in_runs=True)


UPDATE_SHOWN = "update the whole system (repos + AUR)"


def update_cmd(popup: bool | None = None) -> str:
    """What "update everything" does (window) or queues (timed run / root_mode "queue")."""
    if popup is None:
        popup = config.load().get("root_mode", "ask") != "queue"
    return UPDATE_SHOWN if popup else "sudo pacman -Syu --noconfirm"


def pending_updates(timeout: float = 120) -> tuple[bool, list[str]]:
    """Pending updates, read-only (arclightd's checkupdates; else checkupdates here)."""
    try:
        ups = sysapi.call("pkg.list", upgradable=True, _wait=timeout)
        return True, [f"{u['name']} {u.get('version', '')} -> {u.get('new_version', '')}" for u in ups or []]
    except Exception:
        pass
    try:
        r = subprocess.run(["checkupdates", "--nocolor"], capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return r.returncode in (0, 2), [l for l in r.stdout.splitlines() if l.strip()]
    except Exception as e:
        return False, [f"(could not list updates: {e})"]


def update_system(args: dict, ctx: ToolContext) -> ToolResult:
    left = ctx.time_left()
    ok, lines = pending_updates(timeout=max(10, min(120, left)) if left else 120)
    shown = "\n".join(lines[:40]) + (f"\n... and {len(lines) - 40} more" if len(lines) > 40 else "")
    store.log_command("pending updates", 0, "\n".join(lines), "update")
    ctx.on_output((shown or "(everything is up to date)") + "\n")
    if ok and not lines:
        r = ToolResult("Everything is up to date.")
    else:
        try:
            r = _pkg_root(ctx, "Update the system", UPDATE_SHOWN,
                          [f"{len(lines)} updates", "a restore point is made first", "no password needed"],
                          "pkg.upgrade", {"aur": True}, "sudo pacman -Syu --noconfirm", "update_system", queue_in_runs=True)
        except PermissionError as e:
            r = ToolResult(f"not run: {e}", ok=False)
    r.text = f"Pending updates ({len(lines)} packages):\n{shown}\n\n{r.text}"
    return r


# ---------- apps ----------
APP_ALIASES = {
    "browser": ["zen-browser", "firefox", "chromium"], "web": ["zen-browser", "firefox"],
    "internet": ["zen-browser", "firefox"], "files": ["thunar", "nautilus"], "file manager": ["thunar", "nautilus"],
    "explorer": ["thunar"], "terminal": ["ghostty", "kitty"], "console": ["ghostty", "kitty"],
    "shell": ["ghostty", "kitty"], "sound": ["pavucontrol"], "audio": ["pavucontrol"], "volume": ["pavucontrol"],
    "text editor": ["zeditor", "zed", "gnome-text-editor", "gedit"], "editor": ["zeditor", "zed", "gnome-text-editor"],
    "calculator": ["gnome-calculator", "qalculate-gtk"], "settings": ["arclight-settings"],
    "store": ["arclight-store"], "app store": ["arclight-store"],
}


def open_app(args: dict, ctx: ToolContext) -> ToolResult:
    target = str(args.get("target", "")).strip()
    if not target:
        return ToolResult("error: nothing to open", ok=False)
    alias = APP_ALIASES.get(target.lower())
    if alias:
        target = next((a for a in alias if shutil.which(a)), alias[0])
    p = safety.expand(target)
    if target.startswith(("http://", "https://", "file://")) or p.exists():
        cmd = f"xdg-open {json.dumps(target if target.startswith(('http', 'file')) else str(p))}"
    elif shutil.which(target.split()[0]):
        cmd = f"setsid -f {target} >/dev/null 2>&1"
    else:
        cmd = f"gtk-launch {json.dumps(target)}"
    subprocess.Popen(["bash", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    store.log_command(cmd, 0, "launched", "open")
    return ToolResult(f"launched: {cmd}")


def system_info(args: dict, ctx: ToolContext) -> ToolResult:
    def sh(c):
        try:
            return subprocess.run(["bash", "-c", c], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL).stdout.strip()
        except Exception:
            return ""
    info = {
        "hostname": platform.node(),
        "os": sh("grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'"),
        "kernel": platform.release(),
        "uptime": sh("uptime -p"),
        "cpu": sh("lscpu | grep 'Model name' | sed 's/.*: *//'"),
        "gpu": sh("lspci | grep -iE 'vga|display|3d' | sed 's/.*: //' | head -2"),
        "memory": sh("free -h | awk '/Mem:/ {print $3\" used of \"$2}'"),
        "disk_root": sh("df -h / | awk 'NR==2 {print $3\" used of \"$2\" (\"$5\")\"}'"),
        "desktop": sh("hyprctl version 2>/dev/null | head -1") or os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "shell": os.environ.get("SHELL", ""),
        "packages": sh("pacman -Q | wc -l") + " installed",
        "configs": {"hyprland": "~/.config/hypr/hyprland.lua (Eclipse layer: /usr/share/arclight/hypr/arclight.lua)",
                    "bar": "DankMaterialShell", "terminal": "~/.config/ghostty/config", "eclipse-ai": str(config.CONFIG_FILE)},
        "eclipse_tools": "find_settings / change_setting; `arc --help` for the machine API; `arc doctor` checks everything",
        "root_commands": "run as root through arclightd after your yes (no password)" if config.load().get("root_mode", "ask") != "queue" else "queued only",
        "root_review_script": str(rootq.SCRIPT) + (f" ({len(rootq.pending())} waiting)" if rootq.pending() else " (empty)"),
    }
    store.log_command("system_info", 0, "", "info")
    return ToolResult(json.dumps(info, indent=1))


# ---------- Eclipse settings (session daemon) ----------
def find_settings(args: dict, ctx: ToolContext) -> ToolResult:
    q = str(args.get("query", "")).strip()
    if not q:
        return ToolResult("error: give some words to search for", ok=False)
    try:
        rows = (sysapi.call("settings.search", text=q, _wait=20) or [])[:15]
    except Exception as e:
        return ToolResult(f"error: settings are not reachable ({getattr(e, 'message', None) or e})", ok=False)
    lines = []
    for r in rows or []:
        if isinstance(r, dict):
            v = r.get("value")
            ch = f" (one of: {', '.join(map(str, r['choices']))})" if r.get("choices") else ""
            lines.append(f"{r.get('key')} = {json.dumps(v)}  [{r.get('type', '')}] {r.get('description', '')}{ch}")
        else:
            lines.append(str(r))
    store.log_command(f"find settings {q}", 0, "\n".join(lines), "settings")
    return ToolResult("\n".join(lines) or "no settings match")


def change_setting(args: dict, ctx: ToolContext) -> ToolResult:
    key, value = str(args.get("key", "")).strip(), args.get("value", "")
    if not key:
        return ToolResult("error: no setting key", ok=False)
    try:
        before = sysapi.call("settings.get", key=key, _wait=20)
        before = before.get("value") if isinstance(before, dict) else before
    except Exception as e:
        return ToolResult(f"error: unknown setting or settings not reachable ({getattr(e, 'message', None) or e}). "
                          "Use find_settings first.", ok=False)
    ask(ctx, Approval("Change a setting", f"{key}: {json.dumps(before)} → {value}", ["changes how your system works"],
                      heading="Change this setting?", yes="Yes, change it"))
    try:
        res = sysapi.call("settings.set", key=key, value=value, _wait=30)
    except Exception as e:
        return ToolResult(f"error: {getattr(e, 'message', None) or e}", ok=False)
    store.log_command(f"setting {key} = {value}", 0, json.dumps(res)[:1000], "settings")
    return ToolResult(f"{key} changed from {json.dumps(before)} to {value}.")


# ---------- autonomous-only ----------
def update_plan(args: dict, ctx: ToolContext) -> ToolResult:
    if not ctx.run:
        return ToolResult("error: only available in a timed run", ok=False)
    ctx.run.set_plan(str(args.get("plan", "")))
    return ToolResult("plan updated")


def log_progress(args: dict, ctx: ToolContext) -> ToolResult:
    if not ctx.run:
        return ToolResult("error: only available in a timed run", ok=False)
    ctx.run.note(str(args.get("outcome", "tried")), str(args.get("text", "")))
    return ToolResult("noted")


def finish(args: dict, ctx: ToolContext) -> ToolResult:
    if not ctx.run:
        return ToolResult("error: only available in a timed run", ok=False)
    ctx.run.finish_early(str(args.get("completed", "")), str(args.get("verified", "")), str(args.get("still_broken", "")))
    raise StopRun()


HANDLERS = {
    "run_command": run_command, "read_file": read_file, "write_file": write_file, "edit_file": edit_file,
    "install_packages": install_packages, "remove_packages": remove_packages, "open_app": open_app,
    "system_info": system_info, "update_system": update_system,
    "find_settings": find_settings, "change_setting": change_setting,
    "update_plan": update_plan, "log_progress": log_progress, "finish": finish,
}


def describe(name: str, args: dict) -> str:
    """One-line human description shown in the chat before the tool runs."""
    if name == "run_command":
        return str(args.get("command", ""))
    if name == "read_file":
        return f"read {args.get('path', '')}"
    if name in ("write_file", "edit_file"):
        return f"{name.split('_')[0]} {args.get('path', '')}"
    if name == "install_packages":
        return "install " + " ".join(str(x) for x in args.get("packages", []))
    if name == "remove_packages":
        return "remove " + " ".join(str(x) for x in args.get("packages", []))
    if name == "open_app":
        return f"open {args.get('target', '')}"
    if name == "update_system":
        return update_cmd()
    if name == "find_settings":
        return f"find settings: {args.get('query', '')}"
    if name == "change_setting":
        return f"setting {args.get('key', '')} = {args.get('value', '')}"
    if name == "update_plan":
        return "plan: " + str(args.get("plan", ""))[:80].replace("\n", " / ")
    if name == "log_progress":
        return f"{args.get('outcome', '')}: {str(args.get('text', ''))[:100]}"
    if name == "finish":
        return "finish: " + str(args.get("completed", ""))[:100]
    return name


def execute(name: str, args: dict, ctx: ToolContext) -> ToolResult:
    fn = HANDLERS.get(name)
    if not fn:
        return ToolResult(f"error: unknown tool {name}", ok=False)
    try:
        return fn(args or {}, ctx)
    except StopRun:
        raise
    except PermissionError as e:
        return ToolResult(f"not run: {e}", ok=False)
    except Exception as e:
        return ToolResult(f"error: {e}", ok=False)
