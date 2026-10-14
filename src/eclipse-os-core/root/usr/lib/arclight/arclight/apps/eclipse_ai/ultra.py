"""Codex (cloud): OpenAI's Codex CLI as an optional model in Eclipse AI's picker, named as what it is.

It is offered only when the Codex CLI is installed and signed in (`codex login status`). Messages, and the
files Codex reads while working, go to OpenAI's servers; the picker, the chat and every reply say so.
Codex runs its own commands inside its own sandbox (workspace-write, rooted at ~, no root). Those commands do
NOT go through Eclipse AI's approval cards: the window says this when Codex is chosen, and shows every command
as it runs (and writes it to the log, kind "codex"). Root commands come back as `ROOT: sudo …` lines, which
Eclipse AI runs through its normal path: an approval card, then arclightd (which asks for the administrator
password unless passwordless admin is on), or queued in a timed run.
"""
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import time

from . import config, store, tools

MODEL_ID = "ultra"          # the id kept in config files from older versions; shown as NAME
NAME = "Codex (cloud)"
HISTORY = 20          # earlier chat messages sent along
ROOT_RE = re.compile(r"^\s*ROOT:\s*(sudo\s.+?)\s*$", re.M)
DONE_RE = re.compile(r"^\s*GOAL DONE:\s*(.+)$", re.M)
CLOUD_NOTE = ("Codex (cloud): your messages, and the files it reads while working, go to OpenAI. It runs commands itself "
              "in its own sandbox (your home folder, never root) without approval cards; each one is shown here as it runs. "
              "Root commands still need your yes and your password.")
_STATUS = {"t": 0.0, "ok": False}


def available() -> bool:
    """Installed and signed in (checked with `codex login status`, at most once a minute)."""
    if not shutil.which("codex"):
        return False
    if time.time() - _STATUS["t"] < 60:
        return _STATUS["ok"]
    try:
        r = subprocess.run(["codex", "login", "status"], capture_output=True, text=True, timeout=15)
        last = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and not l.startswith("WARNING")]
        ok = r.returncode == 0 and bool(last) and "not logged in" not in last[-1].lower()
    except (OSError, subprocess.SubprocessError):
        ok = False
    _STATUS.update(t=time.time(), ok=ok)
    return ok


def _rules(autonomous: bool) -> str:
    base = f"""You are OpenAI's Codex, used as the cloud model inside Eclipse AI, the desktop assistant of Eclipse OS (an AI-native Arch Linux: Hyprland Wayland compositor, DankMaterialShell bar, ghostty terminal). If asked what you are, say so plainly: Codex by OpenAI, running in the cloud.

The user may type fast or dictate: guess the meaning of typos and act. Never correct spelling. Write short, clear sentences and plain words. Short bullet lists are fine. No markdown headers.

You can run shell commands and edit files inside the home folder yourself. Rules:
- Never use sudo, su, doas or pkexec: they cannot work here. If something truly needs root, do not run it; put each root command on its own line at the very end of your reply, exactly like `ROOT: sudo <command>` (plain sudo on every part, no `cd x && sudo …`, never with yay or paru). The app shows it to the user, who clicks yes and types their password; it then runs as root.
- Never: delete ~, ~/.config, ~/.local, ~/Projects or other whole top-level folders; disk or partition tools; reboot, poweroff, suspend or ending the session; killing Hyprland, pipewire, wireplumber, ghostty, kitty, the bar or ollama; git push --force; piping a download into a shell.
- Before changing a config file, read it and change only the needed lines. Before overwriting an existing file, copy it to <file>.eclipse-ai.bak.
- Check your work with a real command. After acting, confirm what you did in one short line. If something fails, say what failed and one fix.

Facts: user = {config.HOME.name}, home = {config.HOME}. Hyprland config: ~/.config/hypr/hyprland.lua (Lua format, Hyprland 0.56). Terminal: ~/.config/ghostty/config. Eclipse settings: `arc settings search WORDS` and `arc settings set KEY VALUE`. Today: {time.strftime('%A %Y-%m-%d')}."""
    if autonomous:
        base += """

TIMED RUN. Nobody is watching. Work alone toward the goal below: act, verify with real commands, fix, repeat. Do not stop to ask questions. Root commands (ROOT: lines) are only queued for later. When the goal is done and verified, end your reply with one line: `GOAL DONE: <what is done and how you checked it>`."""
    return base


def build_prompt(messages: list[dict], autonomous: bool) -> str:
    """The rules, the earlier conversation (text only) and the current request."""
    convo = [m for m in messages if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()]
    if not convo:
        return _rules(autonomous)
    *earlier, last = convo
    parts = [_rules(autonomous)]
    if earlier:
        lines = []
        for m in earlier[-HISTORY:]:
            who = "User" if m["role"] == "user" else "Eclipse AI"
            lines.append(f"{who}: {str(m['content']).strip()[:2000]}")
        parts.append("Conversation so far:\n" + "\n\n".join(lines))
    parts.append(("Current step:\n" if autonomous else "Current request from the user:\n") + str(last.get("content", "")).strip())
    return "\n\n".join(parts)


def _shown(command: str) -> str:
    """"/usr/bin/bash -lc 'uname -r'" -> "uname -r"."""
    m = re.match(r"^\S*bash\s+-l?c\s+(.+)$", command, re.S)
    if m:
        inner = m.group(1).strip()
        if len(inner) > 1 and inner[0] == inner[-1] == "'":
            inner = inner[1:-1].replace("'\\''", "'")
        elif len(inner) > 1 and inner[0] == inner[-1] == '"':
            inner = inner[1:-1]
        return inner
    return command


def _kill(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except Exception:
            return
        try:
            proc.wait(timeout=2); return
        except subprocess.TimeoutExpired:
            continue


def run(agent, chat, ctx, on_text, on_tool_start, on_tool_done, on_status, use_tools: bool = True,
        num_predict: int | None = None) -> str:
    """Agent.run for Codex (cloud). Returns the final reply text (ROOT: lines removed)."""
    if not available():
        on_text(f"⚠ {NAME} is not set up on this machine.")
        return ""
    prompt = build_prompt(chat.messages, agent.autonomous)
    if not use_tools:
        prompt += "\n\nDo not run any commands. Just answer in text."
    argv = ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--color", "never",
            "-s", "workspace-write" if use_tools else "read-only", "-C", str(config.HOME), prompt]
    env = dict(os.environ)
    env.update(tools.NONINTERACTIVE_ENV)
    on_status("thinking…")
    cards: dict[str, dict] = {}
    texts: list[str] = []
    errors: list[str] = []
    stopped = ""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(config.HOME), env=env, start_new_session=True, text=True, errors="replace")
    except Exception as e:
        on_text(f"⚠ {NAME} could not start ({e})")
        return ""
    agent.proc = proc
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    while True:
        if agent.cancelled or ctx.cancelled:
            stopped = agent.cancel_reason if agent.cancelled else "stopped"; break
        if agent.deadline is not None and time.time() >= agent.deadline:
            stopped = "time is up"; break
        if not sel.select(timeout=0.2):
            if proc.poll() is not None:
                rest = proc.stdout.read()
                for line in rest.splitlines():
                    _event(line, cards, texts, errors, ctx, on_tool_start, on_tool_done, on_status, agent)
                break
            continue
        line = proc.stdout.readline()
        if not line:
            break
        _event(line, cards, texts, errors, ctx, on_tool_start, on_tool_done, on_status, agent)
    sel.close()
    if stopped:
        _kill(proc)
        for c in cards.values():   # commands cut off mid-way
            on_tool_done(c["card"], None, tools.ToolResult(f"[{stopped}]", ok=False))
        on_text(f"\n\n({stopped})")
    else:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill(proc)
    err = ""
    try:
        err = proc.stderr.read() or ""
    except Exception:
        pass
    agent.proc = None

    reply = "\n\n".join(t for t in texts if t.strip()).strip()
    roots = ROOT_RE.findall(reply)
    done = DONE_RE.search(reply)
    shown = ROOT_RE.sub("", reply).strip()
    if shown:
        on_text(shown)
    if not reply and not stopped:
        store.log_command("codex reply", proc.returncode, "\n".join(errors) + "\n" + err[-3000:], "codex")
        on_text(f"⚠ {NAME} did not answer" + (f": {errors[-1][:200]}" if errors else "."))
    chat.messages.append({"role": "assistant", "content": reply or shown})
    chat.save()

    # Root commands go through Eclipse AI's own path: card + arclightd, or queued in a timed run.
    for cmd in roots if not stopped else []:
        card = on_tool_start("run_command", cmd, {"command": cmd})
        ctx.on_output = lambda s, c=card: on_tool_done(c, s, None)
        agent.tool_calls_made += 1
        result = tools.execute("run_command", {"command": cmd}, ctx)
        on_tool_done(card, None, result)
        chat.messages.append({"role": "assistant", "content": f"[root command] {cmd}\n{result.text[:1500]}"})
    if roots and not stopped:
        chat.save()
    if done and ctx.run is not None:
        ctx.run.finish_early(done.group(1).strip(), "see the actions log", "nothing reported")
    on_status("")
    return shown


def _event(line, cards, texts, errors, ctx, on_tool_start, on_tool_done, on_status, agent) -> None:
    try:
        ev = json.loads(line)
    except Exception:
        return
    kind = ev.get("type", "")
    item = ev.get("item") or {}
    itype = item.get("type", "")
    if kind == "item.started" and itype == "command_execution":
        shown = _shown(item.get("command", ""))
        on_status(f"running: {shown[:60]}")
        cards[item.get("id", "")] = {"card": on_tool_start("run_command", shown, {"command": shown}), "shown": shown}
        agent.tool_calls_made += 1
    elif kind == "item.completed" and itype == "command_execution":
        c = cards.pop(item.get("id", ""), None)
        shown = _shown(item.get("command", ""))
        if c is None:
            c = {"card": on_tool_start("run_command", shown, {"command": shown}), "shown": shown}
            agent.tool_calls_made += 1
        out = item.get("aggregated_output", "") or ""
        rc = item.get("exit_code")
        store.log_command(shown, rc, out, "codex")
        if out:
            on_tool_done(c["card"], out, None)
        on_tool_done(c["card"], None, tools.ToolResult(f"exit code: {rc}\n{out.strip() or '(no output)'}", ok=(rc == 0)))
        on_status("thinking…")
    elif kind == "item.completed" and itype == "file_change":
        changes = item.get("changes") or []
        paths = ", ".join(str(ch.get("path", "")) for ch in changes if isinstance(ch, dict)) or "files"
        shown = f"edit {paths}"
        card = on_tool_start("edit_file", shown, {})
        agent.tool_calls_made += 1
        ok = item.get("status", "completed") == "completed"
        store.log_command(shown, 0 if ok else 1, json.dumps(changes)[:3000], "codex")
        on_tool_done(card, None, tools.ToolResult("changed: " + paths, ok=ok))
    elif kind == "item.completed" and itype == "agent_message":
        texts.append(item.get("text", ""))
    elif kind in ("error", "turn.failed"):
        msg = ev.get("message") or (ev.get("error") or {}).get("message", "") or kind
        errors.append(str(msg))
    elif kind == "item.completed" and itype == "error":
        errors.append(str(item.get("message", "")))
