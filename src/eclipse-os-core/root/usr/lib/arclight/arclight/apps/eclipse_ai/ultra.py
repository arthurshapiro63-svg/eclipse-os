"""Eclipse Totality: the strongest model in the picker, shown only by its Eclipse name.
(Arch AI's "Arch Linux Ultra", by Arthur, with the Eclipse name.)

Developer note (never shown in the window): Totality is the Codex CLI (`codex exec --json`),
using Arthur's ChatGPT login in ~/.codex, so these chats go to the cloud (Arthur's one exception
to "local only", kept from Arch AI). Codex runs its own tools inside its workspace-write sandbox
rooted at ~ (no sudo). Eclipse AI's approval cards and hard_block() do NOT see those commands; the
prompt below asks it to avoid the same things. Root commands come back as `ROOT: sudo …` lines,
which Eclipse AI runs through its normal path (approval card + arclightd, or queued in a timed run).
Every Codex command is shown as a tool card and written to the log (kind "ultra"). The window and
the replies never name the engine (`disguise()`).
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

MODEL_ID = "ultra"
NAME = "Eclipse Totality"
HISTORY = 20          # earlier chat messages sent along
ROOT_RE = re.compile(r"^\s*ROOT:\s*(sudo\s.+?)\s*$", re.M)
DONE_RE = re.compile(r"^\s*GOAL DONE:\s*(.+)$", re.M)
# The window never names the engine; errors are cleaned of these words.
_HIDE = re.compile(r"codex|openai|chatgpt|gpt-[\w.-]+", re.I)


# Reply text: whatever it says about itself becomes the Eclipse name (deterministic, the prompt alone is not enough).
_SELF = [
    (re.compile(r"\b(?:OpenAI(?:'s)?\s+)?(?:Codex|ChatGPT)\b(?:\s*(?:CLI|agent))?(?:,?\s*(?:\(|an? AI (?:model|assistant) )?(?:based on|built on|powered by|running on|using)\s+(?:OpenAI(?:'s)?\s+)?GPT-[\w-]+(?:\.\d+)*\)?)?", re.I), NAME),
    (re.compile(r"\b(?:OpenAI(?:'s)?\s+)?GPT-[\w-]+(?:\.\d+)*(?:\s+model)?", re.I), NAME),
    (re.compile(r"\bOpenAI\b", re.I), "Eclipse AI"),
]


def disguise(text: str) -> str:
    for rx, new in _SELF:
        text = rx.sub(new, text)
    n = re.escape(NAME)
    text = re.sub(rf"({n})\s+(?:running|using|on|based on|built on|powered by|via)\s+{n}", r"\1", text)
    text = re.sub(rf"({n})\s+model\b", r"\1", text)
    return re.sub(rf"({n})(?:[,\s]+(?:and|or)?\s*{n})+", r"\1", text)


def available() -> bool:
    return bool(shutil.which("codex")) and (config.HOME / ".codex" / "auth.json").exists()


def _rules(autonomous: bool) -> str:
    base = f"""You are "{NAME}", the strongest model of Eclipse AI, the desktop assistant of Eclipse OS (Arthur's AI-native Arch Linux: Hyprland Wayland compositor, DankMaterialShell bar, ghostty terminal). If asked which model you are, say you are {NAME}, Eclipse AI's top model. Never name any other model, company or tool behind you.

The user is dyslexic and often dictates: guess the meaning of typos and act. Never correct spelling. Write short, clear sentences and plain words. Short bullet lists are fine. No markdown headers.

You can run shell commands and edit files inside the home folder yourself. Rules:
- Never use sudo, su, doas or pkexec: they cannot work here. If something truly needs root, do not run it; put each root command on its own line at the very end of your reply, exactly like `ROOT: sudo <command>` (plain sudo on every part, no `cd x && sudo …`, never with yay or paru). The app shows it to the user, who clicks yes; it then runs as root (no password).
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
    parts.append(f"Remember: in this app you are {NAME}. If the user asks what you are, answer only that you are {NAME}, Eclipse AI's top model.")
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
    """Agent.run for Ultra. Returns the final reply text (ROOT: lines removed)."""
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
        on_text(f"⚠ {NAME} could not start ({_HIDE.sub('engine', str(e))})")
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

    reply = disguise("\n\n".join(t for t in texts if t.strip()).strip())
    roots = ROOT_RE.findall(reply)
    done = DONE_RE.search(reply)
    shown = ROOT_RE.sub("", reply).strip()
    if shown:
        on_text(shown)
    if not reply and not stopped:
        store.log_command("ultra reply", proc.returncode, "\n".join(errors) + "\n" + err[-3000:], "ultra")
        on_text(f"⚠ {NAME} did not answer" + (f": {_HIDE.sub('engine', errors[-1])[:200]}" if errors else "."))
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
        store.log_command(shown, rc, out, "ultra")
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
        store.log_command(shown, 0 if ok else 1, json.dumps(changes)[:3000], "ultra")
        on_tool_done(card, None, tools.ToolResult("changed: " + paths, ok=ok))
    elif kind == "item.completed" and itype == "agent_message":
        texts.append(item.get("text", ""))
    elif kind in ("error", "turn.failed"):
        msg = ev.get("message") or (ev.get("error") or {}).get("message", "") or kind
        errors.append(str(msg))
    elif kind == "item.completed" and itype == "error":
        errors.append(str(item.get("message", "")))
