"""arclight-ask: the system-wide AI prompt (Super+Shift+A).

A glass bar drops in at the top of the screen. Type a request ("make the gaps bigger",
"why is bluetooth broken", "install obs and open it", "play the first level of Geometry
Dash"); an agent with the Arclight tools does it while the bar streams what it is doing.

  arclight-ask                       open the overlay
  arclight-ask --prefill TEXT        open with text already typed (Fix-with-AI notifications)
  arclight-ask --context FILE        attach a file (e.g. a failed unit's log) to the request
  arclight-ask --selection           ask about the selected text / clipboard (Super+Shift+E)
  arclight-ask --cli TEXT            no GUI: run the request and stream progress to the terminal
"""
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from arclight import identity

OS_NAME = identity.os_name()
SHORT = identity.short_name(OS_NAME)

SYSTEM_PROMPT = (
    f"You are {SHORT}, the AI built into this computer ({OS_NAME}, an AI-native Arch Linux). The user asked you "
    "something from the system-wide prompt. Do it fully, using the arclight MCP tools (settings, packages, "
    "services, logs, files, run, screenshot, see, input, ui, apps, games, windows). Changes to the system ask "
    "the user for their administrator password through the system's own prompt; never type or ask for a password "
    "yourself, and if a change is refused, say so. Prefer `settings` for anything that is a setting. Verify the result (read it back, or take a "
    "screenshot for anything visual). Finish with one or two short plain sentences saying what you did; "
    "keep it short and simple. If you truly cannot do it, say exactly why."
)


def agent_cmd(request, agent="claude", model=""):
    if agent == "codex" and shutil.which("codex"):
        return ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "danger-full-access",
                "-c", 'approval_policy="never"', "-C", str(Path.home()), SYSTEM_PROMPT + "\n\nRequest: " + request]
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    cmd = [claude, "-p", request, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "bypassPermissions", "--append-system-prompt", SYSTEM_PROMPT]
    if model:
        cmd += ["--model", model]
    return cmd


# ---------------------------------------------------------------- voice (the Hush dictation engine, all local, when installed)

def hush_bin():
    for c in (shutil.which("hush"), str(Path.home() / ".local/bin/hush"), str(Path.home() / "Projects/hush/hush")):
        if c and os.path.exists(c):
            return c
    return None


def mic_source():
    """Same rule as Hush: the default source does not always resolve, so pick the input node."""
    out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        cols = line.split()
        if len(cols) > 1 and "input" in cols[1] and ".monitor" not in cols[1]:
            return cols[1]
    return None


class Voice:
    def __init__(self):
        self.proc = None
        self.wav = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "arclight" / "ask-voice.wav"

    def start(self):
        self.wav.parent.mkdir(parents=True, exist_ok=True)
        self.wav.unlink(missing_ok=True)
        cmd = ["pw-record", "--format", "s16", "--rate", "16000", "--channels", "1"]
        src = mic_source()
        if src:
            cmd += ["--target", src]
        self.proc = subprocess.Popen(cmd + [str(self.wav)], stderr=subprocess.DEVNULL)

    def stop_and_transcribe(self):
        if self.proc:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        return transcribe(self.wav)


def transcribe(wav):
    h = hush_bin()
    if not h or not Path(wav).exists():
        return ""
    r = subprocess.run([h, "file", str(wav)], capture_output=True, text=True, timeout=120)
    return r.stdout.strip()


def settings():
    try:
        from arclight import client as C
        return {k: C.call("settings.get", key=k)["value"] for k in ("ai.agent", "ai.ask_model")}
    except Exception:
        return {"ai.agent": "claude", "ai.ask_model": ""}


def describe_tool(name, inp):
    short = name.replace("mcp__arclight__", "")
    if not isinstance(inp, dict):
        return short
    bits = [str(inp.get(k)) for k in ("action", "key", "value", "name", "names", "unit", "target", "text", "command",
                                       "query", "keys", "game", "window", "path") if inp.get(k) not in (None, "", [])]
    s = f"{short} {' '.join(bits)}".strip()
    return s[:120]


class Run:
    """One agent run; parses stream-json events into simple progress lines."""

    def __init__(self, request, on_line, on_done):
        self.request, self.on_line, self.on_done = request, on_line, on_done
        self.proc = None
        self.session_id = None
        self.result = None

    def start(self):
        st = settings()
        cmd = agent_cmd(self.request, st.get("ai.agent") or "claude", st.get("ai.ask_model") or "")
        self.agent = st.get("ai.agent") or "claude"
        # argv[0] marker lets arclight-stop find and interrupt it
        self.proc = subprocess.Popen(["bash", "-c", 'exec -a arclight-ask-agent "$@"', "arclight-ask-agent"] + cmd,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     cwd=str(Path.home()),
                                     start_new_session=True)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                self.on_line("·", line[:160])
                continue
            self._event(ev)
        self.proc.wait()
        err = self.proc.stderr.read().strip()
        if self.result is None and err:
            self.result = err[-600:]
        self.on_done(self.result or "(no answer)", self.proc.returncode)

    def _event(self, ev):
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            self.session_id = ev.get("session_id")
            self.on_line("●", "Working on it")
        elif t == "assistant":
            for b in (ev.get("message") or {}).get("content", []):
                if b.get("type") == "tool_use":
                    self.on_line("→", describe_tool(b.get("name", ""), b.get("input")))
                elif b.get("type") == "text" and b.get("text", "").strip():
                    self.on_line("…", b["text"].strip().splitlines()[0][:160])
        elif t == "user":
            for b in (ev.get("message") or {}).get("content", []):
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    c = b.get("content")
                    txt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                    self.on_line("!", txt[:160])
        elif t == "result":
            self.result = ev.get("result") or ev.get("error") or ""
        # codex --json events
        elif t in ("item.completed", "item.started") and isinstance(ev.get("item"), dict):
            it = ev["item"]
            if it.get("type") in ("mcp_tool_call", "command_execution") and t == "item.started":
                self.on_line("→", (it.get("tool") or it.get("command") or "")[:120])
            elif it.get("type") == "agent_message" and t == "item.completed":
                self.result = it.get("text", "")
        elif t == "turn.completed" and self.result is None:
            self.result = ""

    def stop(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGINT)
            time.sleep(1.5)
            if self.proc.poll() is None:
                os.killpg(self.proc.pid, signal.SIGTERM)


# ---------------------------------------------------------------- CLI mode

def cli(request, context=None):
    if context:
        request += f"\n\nContext attached by {SHORT}:\n" + Path(context).read_text(errors="replace")[-20000:]
    done = threading.Event()

    def line(sym, text):
        print(f"\033[38;2;255;201;74m{sym}\033[0m {text}", flush=True)  # sun gold

    def fin(result, code):
        print(f"\n{result}\n", flush=True)
        done.set()

    r = Run(request, line, fin)
    r.start()
    try:
        done.wait()
    except KeyboardInterrupt:
        r.stop()
    return 0


# ---------------------------------------------------------------- overlay

CSS = """
window.ask { background: transparent; backdrop-filter: none; }  /* only the panel is frosted */
/* The panel is a pane of night glass lit by the eclipse: a golden corona halo around it, a bright
   specular top edge, a warm glint in the top-left corner, frosted grain. backdrop-filter makes GTK ask
   the compositor to blur exactly the panel (not the transparent halo margin). */
.panel {
  background-color: rgba($base_rgb, 0.58);
  background-image: MATERIAL;
  border-radius: $r_xl;
  border: 1px solid rgba($gold_rgb, 0.42);
  border-top-color: rgba($gold_soft_rgb, 0.75);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.22), inset 0 0 0 1px rgba($text_rgb, 0.05),
              0 0 0 1px rgba($shadow_rgb, 0.35),
              0 0 22px rgba($gold_rgb, 0.30), 0 0 48px rgba($gold_deep_rgb, 0.20), 0 0 90px rgba($gold_rgb, 0.08),
              0 18px 44px rgba($shadow_rgb, 0.55);
  padding: 16px 18px 14px 18px;
  margin: 40px 56px 64px 56px;
  BACKDROP
}
.panel.working {
  border-color: rgba($gold_rgb, 0.60);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.24), inset 0 0 0 1px rgba($text_rgb, 0.05),
              0 0 26px rgba($gold_rgb, 0.42), 0 0 60px rgba($gold_deep_rgb, 0.28), 0 0 110px rgba($gold_rgb, 0.12),
              0 18px 44px rgba($shadow_rgb, 0.55);
}
/* the little eclipse in the title: a dark disc with a golden rim */
.eclipse-dot {
  min-width: 12px; min-height: 12px; border-radius: 99px;
  background-color: $base;
  box-shadow: 0 0 0 1.5px $gold, 0 0 8px rgba($gold_rgb, 0.85), 0 0 16px rgba($gold_deep_rgb, 0.55);
  margin: 0 4px 0 2px;
}
.title { color: $gold_soft; font-weight: 700; letter-spacing: 2px; font-size: $fs_micro; }
textview.prompt, textview.prompt text {
  background: transparent; color: $text; font-size: $fs_lead; caret-color: $gold;
}
.promptframe {
  border-radius: $r_sm; padding: 10px 14px; min-height: 26px;
  background-color: rgba($sunken_rgb, 0.55);
  box-shadow: inset 0 1px 3px rgba($shadow_rgb, 0.6), inset 0 0 0 1px rgba($text_rgb, 0.08);
}
.promptframe:focus-within {
  box-shadow: inset 0 1px 3px rgba($shadow_rgb, 0.6), inset 0 0 0 1px rgba($gold_rgb, 0.55), 0 0 14px rgba($gold_rgb, 0.18);
}
.log { color: $text_dim; font-family: "JetBrainsMono Nerd Font", monospace; font-size: $fs_micro; }
.answer { color: $text; font-size: $fs_body; }
button.pill {
  background-color: rgba($text_rgb, 0.07); color: $text; border-radius: 999px; padding: 3px 16px; border: none;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.16), inset 0 0 0 1px rgba($text_rgb, 0.08);
}
button.pill:hover { background-color: rgba($gold_rgb, 0.16); box-shadow: inset 0 1px rgba(255,255,255,0.2), inset 0 0 0 1px rgba($gold_rgb, 0.55), 0 0 10px rgba($gold_rgb, 0.20); }
/* the one main action: the sun */
button.go {
  background-image: linear-gradient(to bottom, $gold_soft, $gold 55%, $gold_deep); background-color: $gold;
  color: #1A1205; font-weight: 800; padding: 3px 22px;
  box-shadow: inset 0 1px rgba(255,255,255,0.6), 0 0 14px rgba($gold_rgb, 0.30);
}
button.go:hover { background-color: $gold; box-shadow: inset 0 1px rgba(255,255,255,0.65), 0 0 20px rgba($gold_rgb, 0.50); }
button.go:disabled { background-image: none; background-color: rgba($text_rgb, 0.10); color: rgba($text_rgb, 0.40); box-shadow: none; }
button.stop { background-color: rgba($red_rgb, 0.24); box-shadow: inset 0 1px rgba(255,255,255,0.14), inset 0 0 0 1px rgba($red_rgb, 0.65); }
button.stop:hover { background-color: rgba($red_rgb, 0.42); box-shadow: inset 0 1px rgba(255,255,255,0.14), inset 0 0 0 1px rgba($red_rgb, 0.9); }
.hint { color: $text_dim; font-size: $fs_micro; }
spinner.corona { color: $gold; min-width: 14px; min-height: 14px; }
"""


def overlay(prefill="", context=None, start_voice=False):
    import ctypes
    try:
        ctypes.CDLL("libgtk4-layer-shell.so")
    except OSError:
        pass
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, GLib
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LS
    except (ValueError, ImportError):
        LS = None

    app = Gtk.Application(application_id="dev.arclight.Ask")
    state = {"run": None}

    def activate(app):
        from arclight.apps import glass, motion
        glass.install(CSS.replace("MATERIAL", glass.MATERIAL).replace("BACKDROP", glass.BACKDROP))
        win = Gtk.ApplicationWindow(application=app, title=f"Ask {SHORT}")
        win.add_css_class("ask")
        win.set_default_size(820, -1)
        if LS and LS.is_supported():
            LS.init_for_window(win)
            LS.set_namespace(win, "arclight-ask")
            LS.set_layer(win, LS.Layer.OVERLAY)
            LS.set_anchor(win, LS.Edge.TOP, True)
            LS.set_margin(win, LS.Edge.TOP, 48)
            LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("panel")
        box.set_size_request(820, -1)
        head = Gtk.Box(spacing=8)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("eclipse-dot")
        head.append(dot)
        t = Gtk.Label(label=f"{SHORT.upper()}  ·  ASK", xalign=0)
        t.add_css_class("title")
        t.set_hexpand(True)
        head.append(t)
        spin = Gtk.Spinner(valign=Gtk.Align.CENTER)
        spin.add_css_class("corona")
        spin.set_visible(False)
        head.append(spin)
        hint = Gtk.Label(label="Enter to ask · Esc to close")
        hint.add_css_class("hint")
        head.append(hint)

        def working(on):
            spin.set_visible(on)
            spin.set_spinning(on)
            (box.add_css_class if on else box.remove_css_class)("working")
        box.append(head)
        class Prompt:
            """A wrapping, multi-line prompt (long requests stay readable). Enter runs, Shift+Enter = new line."""

            def __init__(self):
                self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False)
                self.view.add_css_class("prompt")
                self.frame = Gtk.Box()
                self.frame.add_css_class("promptframe")
                self.view.set_hexpand(True)
                self.frame.append(self.view)
                self.buf = self.view.get_buffer()
                self._cb = None
                kc = Gtk.EventControllerKey()
                kc.connect("key-pressed", self._key)
                self.view.add_controller(kc)

            def _key(self, _c, keyval, _code, state):
                if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (state & Gdk.ModifierType.SHIFT_MASK):
                    if self._cb:
                        self._cb(self)
                    return True
                return False

            def connect(self, _sig, cb):
                self._cb = cb

            def get_text(self):
                return self.buf.get_text(self.buf.get_start_iter(), self.buf.get_end_iter(), False)

            def set_text(self, t):
                self.buf.set_text(t)

            def set_position(self, _pos):
                self.buf.place_cursor(self.buf.get_end_iter())

            def grab_focus(self):
                self.view.grab_focus()

            def set_sensitive(self, v):
                self.view.set_sensitive(v)

        entry = Prompt()
        entry.set_text(prefill)
        box.append(entry.frame)
        if not prefill:
            hint2 = Gtk.Label(label="Change, fix, install, open, play… anything on this machine", xalign=0)
            hint2.add_css_class("hint")
            box.append(hint2)
        logbuf = Gtk.Label(xalign=0, wrap=True, selectable=True)
        logbuf.add_css_class("log")
        logbuf.set_visible(False)
        box.append(logbuf)
        answer = Gtk.Label(xalign=0, wrap=True, selectable=True)
        answer.add_css_class("answer")
        answer.set_visible(False)
        box.append(answer)
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        voice = Voice()
        mic_b = Gtk.Button(label="Speak")
        mic_b.add_css_class("pill")
        mic_b.set_visible(bool(hush_bin()))
        mic_b.set_tooltip_text("Click, speak, click again: your words go into the box (local, no cloud)")
        stop_b = Gtk.Button(label="Stop")
        stop_b.add_css_class("pill")
        stop_b.add_css_class("stop")
        stop_b.set_visible(False)
        term_b = Gtk.Button(label="Continue in terminal")
        term_b.add_css_class("pill")
        term_b.set_visible(False)
        go_b = Gtk.Button(label="Ask")
        go_b.add_css_class("pill")
        go_b.add_css_class("go")
        go_b.set_tooltip_text("Or press Enter")
        btns.append(mic_b)
        btns.append(term_b)
        btns.append(stop_b)
        btns.append(go_b)
        box.append(btns)
        win.set_child(box)
        lines = []

        def add_line(sym, text):
            def ui():
                lines.append(f"{sym} {text}")
                logbuf.set_text("\n".join(lines[-12:]))
                if not logbuf.get_visible():
                    motion.rise([logbuf])       # the work log eases in instead of popping
                logbuf.set_visible(True)
            GLib.idle_add(ui)

        def done(result, code):
            def ui():
                answer.set_text(result.strip())
                motion.rise([answer])
                answer.set_visible(True)
                stop_b.set_visible(False)
                go_b.set_visible(True)
                working(False)
                term_b.set_visible(bool(state["run"] and state["run"].session_id))
                entry.set_sensitive(True)
                entry.set_text("")
                entry.grab_focus()
                if not win.is_active():
                    subprocess.Popen(["notify-send", "-a", OS_NAME, "-i", "arclight", f"{SHORT} finished", result[:300]])
            GLib.idle_add(ui)

        def submit(_e):
            req = entry.get_text().strip()
            if not req or (state["run"] and state["run"].proc and state["run"].proc.poll() is None):
                return
            if context:
                req += f"\n\nContext attached by {SHORT}:\n" + Path(context).read_text(errors="replace")[-20000:]
            lines.clear()
            answer.set_visible(False)
            entry.set_sensitive(False)
            stop_b.set_visible(True)
            go_b.set_visible(False)
            working(True)
            add_line("●", "Starting…")
            r = Run(req, add_line, done)
            state["run"] = r
            r.start()

        def on_stop(_b):
            if state["run"]:
                state["run"].stop()
                add_line("■", "Stopped")

        def on_term(_b):
            r = state["run"]
            if r and r.session_id:
                term = os.environ.get("TERMINAL", "ghostty")
                subprocess.Popen([term, "-e", "bash", "-lc", f"cd ~ && claude --resume {shlex.quote(r.session_id)}"],
                                 start_new_session=True)
                win.close()

        def on_mic(_b):
            if voice.proc is None:
                voice.start()
                mic_b.set_label("Done speaking")
                mic_b.add_css_class("stop")
                return
            mic_b.set_label("Writing it down…")
            mic_b.set_sensitive(False)

            def work():
                text = voice.stop_and_transcribe()

                def ui():
                    if text:
                        cur = entry.get_text().strip()
                        entry.set_text((cur + " " + text).strip() if cur else text)
                        entry.set_position(-1)
                    mic_b.set_label("Speak")
                    mic_b.remove_css_class("stop")
                    mic_b.set_sensitive(True)
                    entry.grab_focus()
                GLib.idle_add(ui)
            threading.Thread(target=work, daemon=True).start()

        mic_b.connect("clicked", on_mic)
        entry.connect("activate", submit)
        stop_b.connect("clicked", on_stop)
        go_b.connect("clicked", lambda _b: submit(entry))
        term_b.connect("clicked", on_term)
        keys = Gtk.EventControllerKey()

        def on_key(_c, keyval, _code, _state):
            if keyval == Gdk.KEY_Escape:
                r = state["run"]
                if r and r.proc and r.proc.poll() is None:
                    # keep working in the background; the result arrives as a notification
                    win.set_visible(False)
                    return True
                app.quit()
                return True
            return False

        keys.connect("key-pressed", on_key)
        win.add_controller(keys)
        win.connect("close-request", lambda *_: (app.quit(), False)[1])
        win.present()
        entry.grab_focus()
        entry.set_position(-1)
        if start_voice and hush_bin():
            on_mic(mic_b)

    app.connect("activate", activate)
    app.run([])
    return 0


def selected_text():
    """The highlighted text (primary selection), else the clipboard; never more than 20k characters."""
    for args in (["wl-paste", "--primary", "--no-newline"], ["wl-paste", "--no-newline"]):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout[:20000]
    return ""


def main(argv=None):
    import argparse
    from arclight.aigate import ai_enabled, notify_off, off_text
    if not ai_enabled():
        notify_off()
        print(off_text(), file=sys.stderr)
        return 3
    p = argparse.ArgumentParser(prog="arclight-ask", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("text", nargs="*")
    p.add_argument("--prefill", default="")
    p.add_argument("--context")
    p.add_argument("--cli", action="store_true")
    p.add_argument("--voice", action="store_true", help="open and start listening right away")
    p.add_argument("--selection", action="store_true",
                   help="attach the selected text (or the clipboard) and ask about it (Super+Shift+E)")
    a = p.parse_args(argv)
    text = " ".join(a.text)
    if a.selection:
        sel = selected_text()
        if sel:
            f = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "arclight" / "ask-selection.txt"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(sel)
            a.context = a.context or str(f)
            a.prefill = a.prefill or ("Explain this: " if len(sel) < 400 else "About the text I selected: ")
    if a.cli or (text and not os.environ.get("WAYLAND_DISPLAY")):
        if not text:
            print("arclight-ask --cli needs a request", file=sys.stderr)
            return 2
        return cli(text, a.context)
    return overlay(prefill=a.prefill or text, context=a.context, start_voice=a.voice)
