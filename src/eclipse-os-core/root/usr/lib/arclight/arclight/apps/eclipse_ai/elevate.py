"""Root for approved commands, the Eclipse way: through arclightd, with NO password at all.

Based on Arch AI's elevate.py by Arthur (one polkit popup per batch). On Eclipse OS the root service
arclightd runs root work for members of the `arclight` group, so there is no popup and no password,
but the rest stays exactly as in Arch AI:
- Arthur still sees the exact command(s) in the window and clicks yes first (tools.root_command);
- never in a timed run (nobody is watching): those commands wait in the root review script;
- only commands where every part is plain `sudo cmd` (no flags, nothing mixed, no AUR helpers);
- `safety.hard_block()` still applies;
- once a batch runs as root Eclipse AI cannot kill it: Stop and the wall-clock limit detach and say so;
  a `timeout` inside the root script bounds the commands instead.
The batch is one bash script with a marker line per command (exit code each), run by arclightd's
`exec`; its output goes to a private file in $XDG_RUNTIME_DIR/eclipse-ai that the window follows live.
Every root call is also in arclightd's own action log (`arc actions`).
"""
import os
import re
import secrets
import shlex
import threading
import time

from . import config, rootq, safety, store, sysapi, tools

MARK = "@@eclipse-ai"
AUR_RE = re.compile(r"(^|[\s;&|(/])(yay|paru|makepkg|pikaur|trizen|aurman)(\s|$)")


# ---------- is root possible ----------
def available() -> bool:
    """arclightd answers (its socket exists)."""
    return sysapi.available("system")


# ---------- which commands may go through it ----------
def _spans(command: str) -> tuple[list[tuple[int, int]], str | None]:
    """Split on && || ; | |& and newlines outside quotes. Returns ([(start, end)], error)."""
    spans, start, i, quote, n = [], 0, 0, None, len(command)
    while i < n:
        c = command[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2; continue
            if c == quote:
                quote = None
            i += 1; continue
        if c == "\\":
            i += 2; continue
        if c in "'\"":
            quote = c; i += 1; continue
        if c == "#" and (i == 0 or command[i - 1].isspace()):
            break   # the rest is a comment
        two = command[i:i + 2]
        if two in ("&&", "||", "|&"):
            spans.append((start, i)); i += 2; start = i; continue
        if c in ";|\n":
            spans.append((start, i)); i += 1; start = i; continue
        if c == "&":
            if (i and command[i - 1] in "<>") or command[i + 1:i + 2] == ">":
                i += 1; continue   # a redirect like 2>&1 or &>
            return [], "runs something in the background (&)"
        i += 1
    if quote:
        return [], "has an unclosed quote"
    spans.append((start, n if i >= n else i))
    return [(s, e) for s, e in spans if command[s:e].strip()], None


def check(command: str) -> str | None:
    """None if the command may run as one root batch, else why it must stay queued."""
    cmd = safety.normalize_root(command)
    if not cmd:
        return "empty command"
    if AUR_RE.search(cmd):
        return ("AUR helpers (yay, paru, makepkg) refuse to run as root; use install_packages, which builds AUR "
                "packages as you through Eclipse's package service")
    blocked = safety.hard_block(cmd)
    if blocked:
        return f"never run ({blocked})"
    spans, err = _spans(cmd)
    if err:
        return err
    for s, e in spans:
        part = cmd[s:e].strip()
        try:
            argv = shlex.split(part)
        except ValueError:
            return "could not parse the command"
        if argv and argv[0] in ("doas", "pkexec", "su", "run0", "sudo-rs", "machinectl"):
            return f"uses {argv[0]}; only plain `sudo command` runs as root here"
        if not argv or argv[0] != "sudo":
            return (f"mixed command: '{part[:50]}' does not start with plain sudo. Every part must be `sudo …`; "
                    "run the other parts without sudo in their own call, then the sudo command alone")
        if len(argv) < 2:
            return "sudo with no command"
        if argv[1].startswith("-"):
            return f"`sudo {argv[1]}` has flags; only plain `sudo command` runs as root here"
    return None


def strip_sudo(command: str) -> str:
    """'sudo a && sudo b | sudo c' -> 'a && b | c' (only for commands that pass check())."""
    cmd = safety.normalize_root(command)
    spans, err = _spans(cmd)
    if err:
        return cmd
    for s, e in reversed(spans):
        m = re.match(r"(\s*)sudo\s+", cmd[s:e])
        if m:
            cmd = cmd[:s] + m.group(1) + cmd[s + m.end():]
    return cmd


# ---------- the batch ----------
def build_script(commands: list[str], token: str, limit: int, out_file: str | None = None) -> str:
    """One bash script: a begin marker, then per command a start marker, the command (bounded by
    `timeout` so the whole batch ends within `limit` s) and its exit code. With out_file, everything
    is appended there (the window follows that file live)."""
    env = " ".join(f"{k}={shlex.quote(v)}" for k, v in tools.NONINTERACTIVE_ENV.items() if not k.startswith("SUDO"))
    redirect = f">>{shlex.quote(out_file)} 2>&1" if out_file else "2>&1"
    lines = [
        "set -u",
        f"exec </dev/null {redirect}",
        f"export {env} HOME=/root LANG=C.UTF-8 PATH=/usr/local/sbin:/usr/local/bin:/usr/bin",
        f"cd {shlex.quote(str(config.HOME))} 2>/dev/null || cd /",
        f"M={shlex.quote(f'{MARK}:{token}')}",
        f"end=$((SECONDS + {int(limit)}))",
        'run() { local left=$((end - SECONDS)); if [ "$left" -lt 1 ]; then echo "[skipped: out of time]"; return 124; fi; '
        '/usr/bin/timeout -k 5 "$left" /usr/bin/bash -c "$1"; }',
        'echo "$M begin"',
    ]
    for i, c in enumerate(commands, 1):
        lines += [f'echo "$M start {i}"', f"run {shlex.quote(c)}", f'echo "$M exit {i} $?"']
    lines += ['echo "$M end"', "exit 0"]
    return "\n".join(lines) + "\n"


class _Batch:
    """Parses the marker lines of one running batch."""

    def __init__(self, commands: list[str], token: str, on_output):
        self.commands, self.mark, self.on_output = commands, f"{MARK}:{token}", on_output
        self.began = False
        self.ended = False
        self.cur: int | None = None
        self.codes: list[int | None] = [None] * len(commands)
        self.outs = [""] * len(commands)
        self.pre = ""    # anything before the batch starts
        self.log = ""    # everything, with markers turned into readable lines

    def _text(self, s: str):
        if not s:
            return
        if self.cur is None:
            self.pre += s
        else:
            self.outs[self.cur] += s
        self.log += s
        self.on_output(s)

    def feed(self, line: str):
        idx = line.find(self.mark)
        if idx < 0:
            self._text(line); return
        self._text(line[:idx] + ("\n" if idx else ""))
        parts = line[idx + len(self.mark):].split()
        many = len(self.commands) > 1
        if parts[:1] == ["begin"]:
            self.began = True
            self.on_output("running as root (Eclipse root service, no password)\n")
        elif parts[:1] == ["start"] and len(parts) > 1:
            self.cur = int(parts[1]) - 1
            head = f"# {self.commands[self.cur]}\n"
            self.log += head
            if many:
                self.on_output(head)
        elif parts[:1] == ["exit"] and len(parts) > 2:
            i, rc = int(parts[1]) - 1, int(parts[2])
            self.codes[i] = rc
            self.log += f"-> exit {rc}\n"
            if many:
                self.on_output(f"→ exit {rc}\n")
            self.cur = None
        elif parts[:1] == ["end"]:
            self.ended = True


def _queue_all(pairs: list[tuple[str, str]], ctx, why: str) -> list[str]:
    """Append (command, reason) pairs to the root review script; returns one line each."""
    run_id = getattr(ctx.run, "id", "") if ctx.run else ""
    out = []
    for c, reason in pairs:
        line, added = rootq.add(c, f"{why}: {reason}" if reason else why, run_id)
        ctx.note(f"⏸ needs root, queued for your review: {c}")
        store.log_command(c, None, f"queued in {rootq.SCRIPT} line {line} ({reason})", "root-queue")
        out.append(f"- {c}  ({'queued' if added else 'already queued'}, line {line}{': ' + reason if reason else ''})")
    return out


class _Follower:
    """Reads the batch's output file as it grows and hands complete lines to the batch."""

    def __init__(self, path, batch: _Batch):
        self.path, self.batch, self.pos, self.buf = path, batch, 0, ""

    def poll(self, final: bool = False):
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                data = f.read()
                self.pos += len(data)
        except OSError:
            data = b""
        self.buf += data.decode(errors="replace")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.batch.feed(line + "\n")
        if final and self.buf:
            self.batch.feed(self.buf); self.buf = ""


def run_as_root(commands: list[str], ctx, *, why: str = "root", queue_on_fail: bool = True,
                timeout: float | None = None) -> "tools.ToolResult":
    """Run `commands` (each a plain `sudo …` line, or `arc root …`) as ONE root batch through arclightd.
    Returns a ToolResult with .codes (exit code per command, None = did not run)."""
    R = tools.ToolResult
    commands = [safety.normalize_root(c) for c in commands if c and c.strip()]
    if not commands:
        return R("error: no commands", ok=False)
    if ctx.autonomous:
        lines = _queue_all([(c, "timed runs never run root commands (nobody is watching)") for c in commands], ctx, why)
        return R("NOT RUN: timed runs never run root commands. Queued in the root review script:\n" + "\n".join(lines),
                 ok=False, queued=True, codes=[None] * len(commands))

    good, bad = [], []
    for c in commands:
        reason = check(c)
        (bad if reason else good).append((c, reason))
    skipped = ""
    if bad:
        if queue_on_fail:
            skipped = "NOT RUN (queued in the root review script):\n" + "\n".join(_queue_all(bad, ctx, why))
        else:
            skipped = "NOT RUN (left in the root review script):\n" + "\n".join(f"- {c}  ({r})" for c, r in bad)
    codes_all: dict[str, int | None] = {c: None for c in commands}

    def result(text: str, ok: bool, queued: bool = False, still: bool = False) -> "tools.ToolResult":
        full = "\n\n".join(t for t in (text, skipped) if t)
        return R(full, ok=ok and not bad, queued=queued or (bool(bad) and queue_on_fail and not good),
                 codes=[codes_all[c] for c in commands], still_running=still)

    if not good:
        return result("", ok=False)

    def fall_back(reason: str) -> "tools.ToolResult":
        if queue_on_fail:
            lines = _queue_all([(c, reason) for c, _ in good], ctx, why)
            return result(f"NOT RUN: {reason}. Queued in {rootq.SCRIPT} for the user; do not retry:\n" + "\n".join(lines),
                          ok=False, queued=True)
        return result(f"NOT RUN: {reason}. The commands are still waiting in {rootq.SCRIPT}.", ok=False, queued=True)

    if not available():
        return fall_back("the Eclipse root service (arclightd) is not running")

    root_cmds = [tools.harden(strip_sudo(c)) for c, _ in good]
    limit = int(timeout or ctx.command_timeout)
    token = secrets.token_hex(8)
    config.ensure_dirs()
    out_file = config.RUNTIME_DIR / f"root-{token}.log"
    fd = os.open(out_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.close(fd)
    script = build_script(root_cmds, token, limit, str(out_file))
    batch = _Batch(root_cmds, token, ctx.on_output)
    follow = _Follower(out_file, batch)
    logged = "\n".join(root_cmds)
    box: dict = {}

    def go():
        try:
            box["r"] = sysapi.call("exec", cmd=["/usr/bin/bash", "-c", script], cwd=str(config.HOME),
                                   timeout=limit + 20, _wait=limit + 60)
        except Exception as e:   # delivered below
            box["error"] = e

    worker = threading.Thread(target=go, daemon=True)
    worker.start()
    deadline = time.time() + limit + 30
    status = "done"
    while worker.is_alive():
        worker.join(0.2)
        follow.poll()
        if ctx.cancelled:
            status = "cancelled"; break
        if time.time() > deadline:
            status = "timeout"; break
    follow.poll(final=status == "done")

    if status != "done":
        threading.Thread(target=_drain, args=(worker, follow, batch, logged, out_file), daemon=True).start()
        for c, rc in zip([c for c, _ in good], batch.codes):
            codes_all[c] = rc
        what = "Stop was pressed" if status == "cancelled" else f"the {limit + 30} s limit was reached"
        return result(
            f"{what}, but the commands already run as root and Eclipse AI cannot stop them. They keep running "
            f"in the background (each batch ends by itself within {limit} s) and their output goes to the log "
            f"({config.LOG_DIR / 'commands.log'}). Finished so far:\n{_report(batch)}",
            ok=False, still=True)

    _cleanup(out_file)
    for c, code in zip([c for c, _ in good], batch.codes):
        codes_all[c] = code
    if "error" in box:
        e = box["error"]
        msg = getattr(e, "message", None) or str(e)
        store.log_command(logged, None, batch.log + f"\n[root service error: {msg}]", "root")
        if not batch.began:
            return fall_back(f"the Eclipse root service could not run it ({msg[:200]})")
        return result(f"the root service stopped answering ({msg[:200]}). Finished so far:\n{_report(batch)}", ok=False)
    if not batch.began:
        r = box.get("r") or {}
        store.log_command(logged, r.get("code"), batch.log + (r.get("stderr") or ""), "root")
        return fall_back(f"the root batch did not start (exit {r.get('code')}: {(r.get('stderr') or '').strip()[:200]})")
    store.log_command(logged, _overall(batch.codes), batch.log, "root")
    ok = all(c == 0 for c in batch.codes)
    return result(_report(batch, ctx.max_out), ok=ok)


def _cleanup(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _overall(codes: list[int | None]) -> int | None:
    return next((c for c in codes if c != 0), 0)


def _report(batch: _Batch, limit: int | None = None) -> str:
    limit = limit or tools.MAX_OUT
    if len(batch.commands) == 1:
        rc = batch.codes[0]
        out = batch.outs[0].strip() or "(no output)"
        return f"exit code: {rc} (ran as root)\n{tools._trim(out, limit)}"
    per = max(400, limit // len(batch.commands))
    parts = [f"ran as root ({len(batch.commands)} commands):"]
    for cmd, rc, out in zip(batch.commands, batch.codes, batch.outs):
        state = "did not run" if rc is None else f"exit {rc}" + (" (timed out)" if rc == 124 else "")
        parts.append(f"[{state}] {cmd}\n{tools._trim(out.strip() or '(no output)', per)}")
    return "\n".join(parts)


def _drain(worker, follow, batch, logged, out_file) -> None:
    worker.join(7200)
    follow.poll(final=True)
    _cleanup(out_file)
    store.log_command(logged, _overall(batch.codes), batch.log + "\n[finished in the background after Stop/limit]", "root")


# ---------- the root review queue as one batch ----------
def queue_split() -> tuple[list[str], list[tuple[str, str]]]:
    """Queued commands that can run as one root batch, and the rest with the reason."""
    ok, rest = [], []
    for c in rootq.pending():
        reason = check(c)
        if reason:
            rest.append((c, reason))
        else:
            ok.append(c)
    return ok, rest


def run_queue(ctx, confirm: bool = True) -> "tools.ToolResult":
    """Run every eligible queued command as one batch. Lines that succeed are removed from the root
    review script; failed and ineligible ones stay."""
    cmds, rest = queue_split()
    kept = "\n".join(f"- {c}  ({r})" for c, r in rest)
    if not cmds:
        msg = "Nothing in the root queue can run as one batch." if rest else "Nothing is waiting in the root queue."
        return tools.ToolResult(msg + (f" Still waiting for you:\n{kept}" if rest else ""), ok=not rest, queued=bool(rest))
    n = len(cmds)
    if confirm:
        reasons = ["from the root review script", "runs as root, no password"]
        if rest:
            reasons.append(f"{len(rest)} more stay queued (mixed commands)")
        try:
            tools.ask(ctx, tools.Approval("Root queue", "\n".join(strip_sudo(c) for c in cmds), reasons,
                                          heading=f"Run {n} root command{'s' if n != 1 else ''} now?",
                                          yes="Run now", no="Later", root=True))
        except PermissionError:
            return tools.ToolResult(f"Later: {n} command{'s' if n != 1 else ''} still waiting in {rootq.SCRIPT}.",
                                    ok=False, queued=True)
    r = run_as_root(cmds, ctx, why="root queue", queue_on_fail=False)
    done = [c for c, code in zip(cmds, r.codes or []) if code == 0]
    if done:
        rootq.remove(done)
    left = len(rootq.pending())
    r.text += (f"\n\n{len(done)} of {n} done and removed from {rootq.SCRIPT}; "
               f"{left} still waiting there." + (f"\nNot run as a batch:\n{kept}" if rest else ""))
    return r
