"""Eclipse AI - the GTK4 window (liquid glass). Based on Arch AI's window by Arthur: the same chat,
tool cards, approval cards, duration picker, timed runs, history, quick actions and keys, plus the
Eclipse pages: "AI is off" (Settings -> AI), "Get the AI model" (first start without a model) and
"Install the AI engine" (no ollama)."""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import config, elevate, rootq, store, style, tools, ultra  # noqa: E402
from .agent import Agent  # noqa: E402
from .autonomous import RUNS_DIR, Run, fmt, parse_duration, plain_time  # noqa: E402
from .ollama_client import Ollama, OllamaError  # noqa: E402

ENGINE_PACKAGES = ["ollama", "ollama-vulkan"]
MODEL_HINTS = {"qwen3.5:9b": "Quick. Good for everyday things.", "gemma4:12b": "Smarter, a bit slower.",
               "gpt-oss:20b": "The biggest model on this PC.", "ultra": "The strongest. Goes online."}


def logo_path(size: int = 128) -> str | None:
    here = Path(__file__).resolve()
    for d in (Path("/usr/share/arclight/logo"), here.parents[4] / "art/eclipse/logo/icons"):
        for s in (size, 128, 256, 64):
            p = d / f"eclipse-logo-{s}.png"
            if p.exists():
                return str(p)
    return None


def logo_image(px: int) -> Gtk.Widget:
    p = logo_path(256 if px > 64 else 64)
    if p:
        img = Gtk.Image.new_from_file(p)
    else:
        img = Gtk.Image.new_from_icon_name("arclight")
    img.set_pixel_size(px)
    img.add_css_class("ea-logo")
    return img


# ---------- markdown-lite -> Pango ----------
def _inline(text: str) -> str:
    s = html.escape(text)
    s = re.sub(r"`([^`\n]+)`", r'<span font_family="monospace" foreground="#FFE6B8">\1</span>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    return s


def render_markdown(text: str) -> list[tuple[str, str]]:
    """Return [("text", pango_markup) | ("code", raw)] blocks."""
    blocks, buf = [], []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if buf:
                blocks.append(("text", "\n".join(buf))); buf = []
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            blocks.append(("code", "\n".join(code)))
        else:
            m = re.match(r"^\s*([-*•]|\d+\.)\s+(.*)", line)
            if m:
                bullet = "•" if m.group(1) in "-*•" else m.group(1)
                buf.append(f"  {bullet} " + _inline(m.group(2)))
            elif re.match(r"^#{1,6}\s", line):
                buf.append("<b>" + _inline(re.sub(r"^#{1,6}\s+", "", line)) + "</b>")
            else:
                buf.append(_inline(line))
        i += 1
    if buf:
        blocks.append(("text", "\n".join(buf)))
    return blocks


# ---------- widgets ----------

class Bubble(Gtk.Box):
    """One message. `role` = user | assistant | note."""

    def __init__(self, role: str, text: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.role, self.text = role, text
        self.add_css_class("bubble"); self.add_css_class(f"bubble-{role}")
        self.add_css_class("arc-rise")   # each new message eases up into place (glass.MOTION, real clock)
        self.set_halign(Gtk.Align.END if role == "user" else Gtk.Align.FILL)
        self.set_hexpand(role != "user")
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.append(self.content)
        self.render()

    def append_text(self, delta: str):
        self.text += delta
        self.render()

    def render(self):
        self.set_visible(bool(self.text.strip()) or self.role != "assistant")
        child = self.content.get_first_child()
        while child:
            self.content.remove(child); child = self.content.get_first_child()
        blocks = render_markdown(self.text) if self.role != "user" else [("text", html.escape(self.text))]
        if not blocks:
            blocks = [("text", "")]
        for kind, body in blocks:
            if kind == "code":
                lab = Gtk.Label(label=body, xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
                lab.add_css_class("code-block")
            else:
                lab = Gtk.Label(xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, use_markup=True)
                try:
                    lab.set_markup(body)
                except Exception:
                    lab.set_text(re.sub(r"<[^>]+>", "", body))
            lab.set_max_width_chars(90)
            self.content.append(lab)


TOOL_KIND = {"run_command": "$", "read_file": "read", "write_file": "write", "edit_file": "edit",
             "install_packages": "install", "remove_packages": "remove", "open_app": "open", "system_info": "info",
             "root_queue": "#", "find_settings": "settings", "change_setting": "setting", "update_system": "update",
             "update_plan": "plan", "log_progress": "note", "finish": "done"}


class ToolCard(Gtk.Box):
    """Shows the exact command, then its output."""

    def __init__(self, name: str, shown: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("tool-card")
        self.add_css_class("arc-rise")
        head = Gtk.Box(spacing=8)
        self.status = Gtk.Label(label="▶"); self.status.add_css_class("tool-status")
        head.append(self.status)
        title = Gtk.Label(label=TOOL_KIND.get(name, name))
        title.add_css_class("tool-kind"); head.append(title)
        cmd = Gtk.Label(label=shown, xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, hexpand=True)
        cmd.add_css_class("tool-cmd"); head.append(cmd)
        self.append(head)
        self.out = Gtk.Label(xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, visible=False)
        self.out.add_css_class("tool-out")
        self.out_text = ""
        self.expander = Gtk.Expander(label="output", visible=False)
        self.expander.set_child(self.out)
        self.append(self.expander)

    def add_output(self, s: str):
        self.out_text += s
        shown = self.out_text if len(self.out_text) < 4000 else self.out_text[:2000] + "\n…\n" + self.out_text[-1500:]
        self.out.set_text(shown.rstrip("\n"))
        self.out.set_visible(True); self.expander.set_visible(True)
        self.expander.set_expanded(len(self.out_text) < 1200)

    def finish(self, result: tools.ToolResult):
        if result.still_running:
            # Stop / the limit came after it started as root: it cannot be killed from here.
            self.status.set_text("⚠"); self.status.add_css_class("queued")
            note = Gtk.Label(label="Still running as root. Stop cannot end it; it ends by itself. Output goes to the log.",
                             xalign=0, wrap=True)
            note.add_css_class("dim"); self.append(note)
        elif result.queued:
            self.status.set_text("⏸"); self.status.add_css_class("queued")
        else:
            self.status.set_text("✔" if result.ok else "✖")
            self.status.add_css_class("ok" if result.ok else "fail")
        if not self.out_text:
            self.add_output(result.text)
            self.expander.set_expanded(len(result.text) < 400)


class ApprovalCard(Gtk.Box):
    """Inline permission request (yes / no), always with the exact command(s). There is never a password
    box in the app and, on Eclipse OS, no password popup either: a root command runs through arclightd
    right after "yes"."""

    def __init__(self, approval: tools.Approval, on_answer):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("approval-card")
        if approval.root:
            self.add_css_class("approval-root")
        self.approval, self.on_answer = approval, on_answer
        top = Gtk.Box(spacing=10)
        t = Gtk.Label(label=approval.heading or f"{approval.title}?", xalign=0, wrap=True, hexpand=True)
        t.add_css_class("approval-title"); top.append(t)
        if approval.root:
            tag = Gtk.Label(label="as root", valign=Gtk.Align.CENTER)
            tag.add_css_class("approval-tag"); tag.add_css_class("root"); top.append(tag)
        self.append(top)
        cmd = Gtk.Label(label=approval.command, xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        cmd.add_css_class("approval-cmd"); self.append(cmd)
        if approval.preview:
            pv = Gtk.Label(label=approval.preview, xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
            pv.add_css_class("code-block"); self.append(pv)
        why = Gtk.Label(label="Why I ask: " + ", ".join(approval.reasons), xalign=0, wrap=True); why.add_css_class("dim")
        self.append(why)
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        no = Gtk.Button(label=approval.no); no.connect("clicked", lambda *_: self._answer(False))
        yes = Gtk.Button(label=approval.yes); yes.add_css_class("suggested-action"); yes.connect("clicked", lambda *_: self._answer(True))
        btns.append(no); btns.append(yes); self.append(btns)
        self.buttons = (no, yes)
        GLib.idle_add(lambda: yes.grab_focus() and False)   # once (a True return would repeat it forever)

    def _answer(self, ok: bool):
        for b in self.buttons:
            b.set_sensitive(False)
        self.approval.approved = ok
        self.add_css_class("answered-yes" if ok else "answered-no")
        self.on_answer(self)


class RunStrip(Gtk.Box):
    """The timed run, live: goal, time used and left, step, last action, and the sun's progress
    (elapsed / budget, from the real clock)."""

    def __init__(self, on_stop):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=12, margin_end=12, margin_bottom=6)
        self.add_css_class("ea-run")
        row = Gtk.Box(spacing=10)
        self.title = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.title.add_css_class("ea-run-title")
        row.append(self.title)
        stop = Gtk.Button(label="Stop the run")
        stop.add_css_class("destructive-action")
        stop.connect("clicked", lambda *_: on_stop())
        row.append(stop)
        self.append(row)
        self.bar = Gtk.ProgressBar()
        self.append(self.bar)
        self.meta = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.meta.add_css_class("ea-run-meta")
        self.append(self.meta)
        self.set_visible(False)

    def show_status(self, st: dict):
        self.set_visible(True)
        self.title.set_text(f"Working alone on: {st.get('goal', '')}")
        budget = max(1, int(st.get("budget") or 1))
        self.bar.set_fraction(min(1.0, max(0.0, st.get("elapsed", 0) / budget)))
        self.meta.set_text(f"{fmt(st.get('elapsed', 0))} done · {fmt(st.get('remaining', 0))} left · "
                           f"step {st.get('step', 0)} · {st.get('last', '')}")


# ---------- window ----------
class Window(Gtk.ApplicationWindow):
    DURATIONS = [("Reply once", 0), ("Work 10 min", 600), ("Work 30 min", 1800), ("Work 1 hour", 3600),
                 ("Work 2 hours", 7200), ("Work 3 hours", 10800)]

    def __init__(self, app, import_note: str = ""):
        cfg = config.load()
        w, h = (cfg.get("window") or [980, 720])[:2]
        super().__init__(application=app, title=config.APP_NAME, default_width=int(w), default_height=int(h))
        self.add_css_class("eclipse-ai")
        self.set_icon_name("arclight")
        self.cfg = cfg
        self.zoom_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.zoom_css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        self.apply_font_size()
        self.client = Ollama(self.cfg["host"])
        self.agent: Agent | None = None
        self.run: Run | None = None
        self.run_thread: threading.Thread | None = None
        self.ctx: tools.ToolContext | None = None
        self.busy = False
        self.started_server = False
        self.pulling: Ollama | None = None
        self.chat: store.Chat = store.latest_chat() or store.Chat()
        self._models: list[str] = [self.cfg["model"]]

        # header: logo + name, new chat, history | model picker, menu
        hb = Gtk.HeaderBar()
        self.set_titlebar(hb)
        tbox = Gtk.Box(spacing=8)
        tbox.append(logo_image(22))
        title = Gtk.Label(label=config.APP_NAME); title.add_css_class("ea-title")
        tbox.append(title)
        hb.set_title_widget(tbox)
        new_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New chat  (Ctrl+N)")
        new_btn.connect("clicked", lambda *_: self.new_chat()); hb.pack_start(new_btn)
        self.new_btn = new_btn
        self.hist_btn = Gtk.MenuButton(icon_name="document-open-recent-symbolic", tooltip_text="Earlier chats")
        hb.pack_start(self.hist_btn)
        hb.pack_end(self._menu_button())
        hb.pack_end(self._model_picker())

        # pages: chat | off | setup
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=220)
        self.set_child(self.stack)
        self.stack.add_named(self._chat_page(), "chat")
        self.stack.add_named(self._off_page(), "off")
        self.setup = self._setup_page()
        self.stack.add_named(self.setup, "setup")

        # shortcuts
        sc = Gtk.ShortcutController()
        def short(keys, fn):
            sc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(keys), Gtk.CallbackAction.new(lambda *_: fn() or True)))
        short("<Control>n", self.new_chat)
        short("<Control>q", self.close)
        short("<Control>w", self.close)
        short("Escape", self.stop)
        for keys, delta in (("<Control>plus|<Control>equal|<Control>KP_Add", 1), ("<Control>minus|<Control>KP_Subtract", -1),
                            ("<Control>0|<Control>KP_0", 0)):
            short(keys, lambda d=delta: self.zoom(d))
        short("<Control>l", lambda: self.entry.grab_focus())
        self.add_controller(sc)
        self.connect("close-request", self._on_close)
        self.connect("notify::is-active", self._on_active)

        self._rebuild_history_menu()
        self.replay(self.chat)
        if import_note:
            self._note(import_note)
        if config.ai_enabled():
            self.stack.set_visible_child_name("chat")
            self.entry.grab_focus()
            threading.Thread(target=self._boot_server, daemon=True).start()
        else:
            self.stack.set_visible_child_name("off")

    # ----- pages -----
    def _chat_page(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroller.add_css_class("ea-scroll")
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_bottom=12,
                            margin_start=18, margin_end=18)
        self.scroller.set_child(self.list)
        self.stick = True
        self.scroller.get_vadjustment().connect("value-changed", self._on_scrolled)
        root.append(self.scroller)
        self.runstrip = RunStrip(self.stop)
        root.append(self.runstrip)
        self.status = Gtk.Label(label="", xalign=0, margin_start=20, margin_bottom=3, ellipsize=Pango.EllipsizeMode.END)
        self.status.add_css_class("statusline")
        root.append(self.status)
        bottom = Gtk.Box(spacing=8, margin_start=14, margin_end=14, margin_bottom=14)
        self.entry = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True, accepts_tab=False)
        self.entry.add_css_class("entry")
        self.entry.set_top_margin(10); self.entry.set_bottom_margin(10); self.entry.set_left_margin(12); self.entry.set_right_margin(12)
        ek = Gtk.EventControllerKey(); ek.connect("key-pressed", self._entry_key); self.entry.add_controller(ek)
        esw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, max_content_height=160, propagate_natural_height=True)
        esw.set_child(self.entry); esw.add_css_class("entry-frame")
        bottom.append(esw)
        self.dur_dd = Gtk.DropDown.new_from_strings([d[0] for d in self.DURATIONS])
        self.dur_dd.set_tooltip_text("How long to keep working on it alone (timed mode).\nOr type: /work 45m <goal>")
        self.dur_dd.set_valign(Gtk.Align.END); self.dur_dd.add_css_class("duration")
        bottom.append(self.dur_dd)
        self.send_btn = Gtk.Button(icon_name="mail-send-symbolic", tooltip_text="Send (Enter)", valign=Gtk.Align.END)
        self.send_btn.add_css_class("suggested-action"); self.send_btn.connect("clicked", lambda *_: self.send())
        self.stop_btn = Gtk.Button(icon_name="media-playback-stop-symbolic", tooltip_text="Stop (Esc)", valign=Gtk.Align.END,
                                   visible=False)
        self.stop_btn.add_css_class("destructive-action"); self.stop_btn.connect("clicked", lambda *_: self.stop())
        bottom.append(self.send_btn); bottom.append(self.stop_btn)
        root.append(bottom)
        return root

    def _card_page(self, cls: str = ""):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER,
                        margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, width_request=520)
        card.add_css_class("ea-card")
        if cls:
            card.add_css_class(cls)
        card.append(logo_image(112))
        outer.append(card)
        return outer, card

    def _off_page(self):
        try:
            from arclight.edition import has_ai
            core = not has_ai()
        except ImportError:
            core = False
        outer, card = self._card_page("off")
        t = Gtk.Label(label="This edition has no built-in AI" if core else "AI features are turned off", wrap=True,
                      justify=Gtk.Justification.CENTER)
        t.add_css_class("ea-card-title"); card.append(t)
        line = Gtk.Box(width_request=260, halign=Gtk.Align.CENTER); line.add_css_class("corona-line"); card.append(line)
        s = Gtk.Label(label=("Claude Code can still run this whole PC.\nPress Super+A, or type claude in a terminal."
                             if core else "Turn them on in Settings → AI.\nThen Eclipse AI is ready again."), wrap=True,
                      justify=Gtk.Justification.CENTER)
        s.add_css_class("ea-card-text"); card.append(s)
        if core:
            return outer
        btns = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER, margin_top=8)
        again = Gtk.Button(label="Check again"); again.connect("clicked", lambda *_: self.check_enabled())
        go = Gtk.Button(label="Open Settings → AI"); go.add_css_class("ea-gold"); go.add_css_class("ea-big")
        go.connect("clicked", lambda *_: self._spawn(["arclight-settings", "--page", "ai"]))
        btns.append(again); btns.append(go)
        card.append(btns)
        return outer

    def _setup_page(self):
        outer, card = self._card_page()
        self.setup_title = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.setup_title.add_css_class("ea-card-title"); card.append(self.setup_title)
        line = Gtk.Box(width_request=260, halign=Gtk.Align.CENTER); line.add_css_class("corona-line"); card.append(line)
        self.setup_text = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=54)
        self.setup_text.add_css_class("ea-card-text"); card.append(self.setup_text)
        self.setup_bar = Gtk.ProgressBar(visible=False, margin_top=6)
        card.append(self.setup_bar)
        self.setup_detail = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, visible=False)
        self.setup_detail.add_css_class("ea-card-small"); card.append(self.setup_detail)
        btns = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER, margin_top=8)
        self.setup_cancel = Gtk.Button(label="Cancel", visible=False)
        self.setup_cancel.connect("clicked", lambda *_: self._cancel_setup())
        self.setup_btn = Gtk.Button(); self.setup_btn.add_css_class("ea-gold"); self.setup_btn.add_css_class("ea-big")
        self.setup_btn.connect("clicked", lambda *_: self._setup_action())
        btns.append(self.setup_cancel); btns.append(self.setup_btn)
        card.append(btns)
        self.setup_small = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=60)
        self.setup_small.add_css_class("ea-card-small"); card.append(self.setup_small)
        self.setup_kind = ""
        return outer

    def show_setup(self, kind: str, error: str = ""):
        """kind: model (no model yet) | engine (ollama missing) | server (did not start)."""
        self.setup_kind = kind
        self.setup_bar.set_visible(False); self.setup_detail.set_visible(False); self.setup_cancel.set_visible(False)
        self.setup_btn.set_sensitive(True)
        if kind == "model":
            gb = float(self.cfg.get("starter_size_gb", 6.6))
            name = config.display_name(self.cfg, self.cfg.get("starter_model", "qwen3.5:9b"))
            self.setup_title.set_text("Get the AI model")
            self.setup_text.set_text(f"Eclipse AI thinks on this PC, not in the cloud. It needs its model once: "
                                     f"{name}, a {gb:g} GB download.")
            self.setup_btn.set_label(f"Get the AI model ({gb:g} GB)")
            self.setup_small.set_text("You can keep using the PC while it downloads. If it stops, press it again: "
                                      "it carries on where it was.")
        elif kind == "engine":
            self.setup_title.set_text("The AI engine is missing")
            self.setup_text.set_text("Eclipse AI needs its engine (Ollama) to run models on this PC.")
            self.setup_btn.set_label("Install it (about 100 MB)")
            self.setup_small.set_text("Installed by Eclipse's package service. A restore point is made first. No password.")
        else:
            self.setup_title.set_text("The AI engine did not start")
            self.setup_text.set_text("Something stopped the model server from starting.")
            self.setup_btn.set_label("Try again")
            self.setup_small.set_text(f"Details: systemctl --user status {config.OLLAMA_UNIT}")
        if error:
            self.setup_detail.set_text(error); self.setup_detail.set_visible(True)
        self.stack.set_visible_child_name("setup")

    def _setup_action(self):
        if self.setup_kind == "model":
            self.pull_model()
        elif self.setup_kind == "engine":
            self.install_engine()
        else:
            self.setup_btn.set_sensitive(False)
            threading.Thread(target=self._boot_server, daemon=True).start()

    def _cancel_setup(self):
        if self.pulling:
            self.pulling._cancelled_by_user = True
            self.pulling.cancel()

    # ----- model download (time-based progress: bytes and the real clock) -----
    def pull_model(self, model: str | None = None):
        model = model or self.cfg.get("starter_model", "qwen3.5:9b")
        self.setup_btn.set_sensitive(False)
        self.setup_cancel.set_visible(True)
        self.setup_bar.set_visible(True); self.setup_bar.set_fraction(0.0)
        self.setup_detail.set_visible(True); self.setup_detail.set_text("Starting the download…")
        client = Ollama(self.cfg["host"])
        self.pulling = client

        def work():
            done_bytes: dict[str, tuple[int, int]] = {}
            first = None     # (clock, bytes) when bytes were first seen: a resumed download starts part-way
            err = ""
            try:
                for ch in client.pull(model):
                    st = ch.get("status", "")
                    if ch.get("digest") and ch.get("total"):
                        done_bytes[ch["digest"]] = (int(ch.get("completed") or 0), int(ch["total"]))
                    have = sum(c for c, _ in done_bytes.values())
                    total = sum(t for _, t in done_bytes.values()) or 1
                    now = time.monotonic()
                    if done_bytes and first is None:
                        first = (now, have)
                    left = ""
                    if first and now - first[0] > 3 and have > first[1]:
                        rate = (have - first[1]) / (now - first[0])          # bytes per real second
                        left = f" · about {fmt((total - have) / rate)} left"
                    text = (f"{have / 1e9:.1f} of {total / 1e9:.1f} GB{left}" if done_bytes and have < total
                            else {"verifying sha256 digest": "Checking the download…", "writing manifest": "Almost done…",
                                  "success": "Done."}.get(st, "Getting ready…"))
                    GLib.idle_add(self._pull_progress, have / total if done_bytes else 0.0, text)
            except Exception as e:
                err = "stopped" if getattr(self.pulling, "_cancelled_by_user", False) else str(e)
            GLib.idle_add(self._pull_done, model, err)

        threading.Thread(target=work, daemon=True).start()

    def _pull_progress(self, frac, text):
        self.setup_bar.set_fraction(frac)
        self.setup_detail.set_text(text)
        return False

    def _pull_done(self, model, err):
        self.pulling = None
        if err:
            self.show_setup("model", f"The download stopped ({err[:160]}). Press the button to carry on.")
            return False
        if model not in self.client.models():
            self.show_setup("model", "The download did not finish. Press the button to carry on.")
            return False
        self.cfg["model"] = model
        config.save(self.cfg)
        self._after_server_up()
        return False

    # ----- engine install through arclightd -----
    def install_engine(self):
        self.setup_btn.set_sensitive(False)
        self.setup_bar.set_visible(True); self.setup_bar.pulse()
        self.setup_detail.set_visible(True); self.setup_detail.set_text("Installing…")
        if not elevate.available():
            self.show_setup("engine", "The Eclipse package service (arclightd) is not running. Try `arc doctor`.")
            return
        last = {"t": time.monotonic()}

        def line(s):
            def ui():
                if time.monotonic() - last["t"] > 0.15:
                    self.setup_bar.pulse(); last["t"] = time.monotonic()
                self.setup_detail.set_text(s.strip()[-90:])
                return False
            GLib.idle_add(ui)

        def work():
            try:
                tools.pkg_job("pkg.install", {"names": ENGINE_PACKAGES, "aur": False}, line)
                err = ""
            except Exception as e:
                err = str(e)
            def done():
                if err:
                    self.show_setup("engine", f"It did not install: {err[:200]}")
                else:
                    self.setup_detail.set_text("Installed. Starting it…")
                    threading.Thread(target=self._boot_server, daemon=True).start()
                return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()

    # ----- the global AI switch -----
    def check_enabled(self) -> bool:
        on = config.ai_enabled()
        # with the AI off the chat controls do nothing: show only the card (and the menu)
        for w in (getattr(self, "new_btn", None), getattr(self, "hist_btn", None), getattr(self, "model_btn", None)):
            if w is not None:
                w.set_visible(on)
        if not on:
            if self.busy:
                self.stop()
            self.stack.set_visible_child_name("off")
        elif self.stack.get_visible_child_name() == "off":
            self.stack.set_visible_child_name("chat")
            threading.Thread(target=self._boot_server, daemon=True).start()
        return on

    def _on_active(self, *_):
        if self.is_active() and not self.busy:
            self.check_enabled()

    # ----- look -----
    def apply_font_size(self):
        pt = max(8, min(22, int(self.cfg.get("font_size", 11))))
        # the window's base size; everything else is relative (em), so headings stay bigger
        self.zoom_css.load_from_string(f"window.eclipse-ai, window.eclipse-ai textview {{ font-size: {pt}pt; }}")

    def zoom(self, delta: int):
        self.cfg["font_size"] = 11 if delta == 0 else int(self.cfg.get("font_size", 11)) + delta
        self.apply_font_size(); config.save(self.cfg)
        self.status.set_text(f"text size: {self.cfg['font_size']}pt  (Ctrl + / Ctrl - / Ctrl 0)")

    def alias(self, model: str) -> str:
        return config.display_name(self.cfg, model, self._models.index(model) if model in self._models else 0)

    # ----- model picker -----
    def _model_picker(self):
        self.model_btn = Gtk.MenuButton(tooltip_text="Model")
        self.model_btn.add_css_class("ea-model")
        box = Gtk.Box(spacing=8)
        self.model_dot = Gtk.Box(valign=Gtk.Align.CENTER); self.model_dot.add_css_class("ea-dot")
        self.model_label = Gtk.Label(label=self.alias(self.cfg["model"]))
        box.append(self.model_dot); box.append(self.model_label)
        box.append(Gtk.Image.new_from_icon_name("pan-down-symbolic"))
        self.model_btn.set_child(box)
        self.model_pop = Gtk.Popover(has_arrow=False)
        self.model_pop.add_css_class("ea-pop")
        self.model_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.model_list.connect("row-activated", self._model_row)
        self.model_pop.set_child(self.model_list)
        self.model_btn.set_popover(self.model_pop)
        self._fill_models(list(self._models), quiet=True)
        return self.model_btn

    def _fill_models(self, models: list[str], quiet: bool = False):
        if ultra.available() and ultra.MODEL_ID not in models:
            models.append(ultra.MODEL_ID)   # always the last entry
        if not models:
            return False
        if self.cfg["model"] not in models:
            if quiet:
                models.append(self.cfg["model"])
            else:
                order = [m for m in config.MODEL_NAMES if m in models and m != ultra.MODEL_ID]
                self.cfg["model"] = order[0] if order else models[0]
                config.save(self.cfg)
        self._models = models
        child = self.model_list.get_first_child()
        while child:
            self.model_list.remove(child); child = self.model_list.get_first_child()
        for i, m in enumerate(models):
            row = Gtk.ListBoxRow()
            row.model_id = m
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            n = Gtk.Label(label=config.display_name(self.cfg, m, i), xalign=0); n.add_css_class("ea-mname")
            hint = MODEL_HINTS.get(m, "On this PC.")
            h = Gtk.Label(label=hint, xalign=0); h.add_css_class("ea-mhint")
            v.append(n); v.append(h)
            row.set_child(v)
            if m == self.cfg["model"]:
                row.add_css_class("ea-current")
            self.model_list.append(row)
        self._show_model()
        return False

    def _show_model(self):
        self.model_label.set_text(self.alias(self.cfg["model"]))
        if self.cfg["model"] == ultra.MODEL_ID:
            self.model_dot.add_css_class("online")
        else:
            self.model_dot.remove_css_class("online")

    def _model_row(self, _lb, row):
        self.model_pop.popdown()
        m = getattr(row, "model_id", None)
        if m and m != self.cfg["model"]:
            self.cfg["model"] = m; config.save(self.cfg)
            self._fill_models(list(self._models))
            self.status.set_text(f"model: {self.alias(m)}")

    # ----- menu -----
    def _menu_button(self):
        menu = Gio.Menu()
        menu.append("Bigger text  (Ctrl +)", "win.zoom-in")
        menu.append("Smaller text  (Ctrl -)", "win.zoom-out")
        menu.append("Open log folder", "win.logs")
        menu.append("Open config", "win.config")
        menu.append("Root review script (needs you)", "win.rootq")
        menu.append("Run root queue now", "win.rootrun")
        menu.append("Run folders", "win.runs")
        menu.append("Delete this chat", "win.delete")
        for name, cb in (("logs", lambda *_: self._spawn(["xdg-open", str(config.LOG_DIR)])),
                         ("zoom-in", lambda *_: self.zoom(1)), ("zoom-out", lambda *_: self.zoom(-1)),
                         ("config", lambda *_: self._spawn(["xdg-open", str(config.CONFIG_FILE)])),
                         ("rootq", lambda *_: self.show_root_queue()),
                         ("rootrun", lambda *_: self.run_root_queue()),
                         ("runs", lambda *_: self.open_runs()),
                         ("delete", lambda *_: self.delete_chat())):
            a = Gio.SimpleAction.new(name, None); a.connect("activate", cb); self.add_action(a)
        return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)

    @staticmethod
    def _spawn(argv):
        try:
            subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    # ----- chats -----
    def _rebuild_history_menu(self):
        menu = Gio.Menu()
        for c in store.list_chats()[:15]:
            when = time.strftime("%b %d %H:%M", time.localtime(c["updated"]))
            menu.append(f"{when}  {c['title'][:40]}", f"win.open-chat::{c['id']}")
        if not self.lookup_action("open-chat"):
            a = Gio.SimpleAction.new("open-chat", GLib.VariantType.new("s"))
            a.connect("activate", lambda _a, p: self.open_chat(p.get_string())); self.add_action(a)
        self.hist_btn.set_menu_model(menu)

    def open_chat(self, chat_id: str):
        if self.busy:
            return
        p = config.CHAT_DIR / f"{chat_id}.json"
        if p.exists():
            self.chat = store.Chat.load(p); self.replay(self.chat)

    def new_chat(self):
        if self.busy or not self.chat.messages:
            return
        self.chat = store.Chat()
        self.replay(self.chat); self._rebuild_history_menu(); self.entry.grab_focus()

    def delete_chat(self):
        if self.busy:
            return
        self.chat.delete(); self.chat = store.Chat(); self.replay(self.chat); self._rebuild_history_menu()

    def _clear_list(self):
        child = self.list.get_first_child()
        while child:
            self.list.remove(child); child = self.list.get_first_child()

    def _hello(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=6)
        top = Gtk.Box(spacing=14)
        top.append(logo_image(56))
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        h = Gtk.Label(label="Hi, I'm Eclipse AI.", xalign=0); h.add_css_class("ea-hello")
        line = Gtk.Box(width_request=220, halign=Gtk.Align.START); line.add_css_class("corona-line")
        s = Gtk.Label(label="I run on this PC. Ask me to fix, change, install or explain anything.", xalign=0, wrap=True)
        s.add_css_class("ea-hello-sub")
        txt.append(h); txt.append(line); txt.append(s)
        top.append(txt)
        box.append(top)
        return box

    QUICK = [("Update my system", "Update everything on my system."),
             ("How is my PC doing?", "Give me a short health check: CPU, memory, disk, temperatures, failed services."),
             ("Free up disk space", "Find what is taking disk space and suggest safe ways to free some."),
             ("Make the gaps bigger", "Make the gaps between my windows a bit bigger."),
             ("What's slow right now?", "Show me the processes using the most CPU and memory right now."),
             ("My keybinds", "List my Hyprland keybinds in a short readable list.")]

    def _quick_actions(self):
        box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, min_children_per_line=2,
                          column_spacing=8, row_spacing=8, homogeneous=True)
        box.add_css_class("quick")
        for label, prompt in self.QUICK:
            b = Gtk.Button(label=label); b.add_css_class("quick-btn")
            b.connect("clicked", lambda _b, t=prompt: self.send(t))
            box.append(b)
        return box

    def replay(self, chat: store.Chat):
        self._clear_list()
        if not chat.events:
            self.list.append(self._hello())
            self.list.append(Bubble("note", "Tip: pick “Work 30 min” and I keep going on my own until the job is done "
                                            "or the time is up. Before I change the system, you see the exact command "
                                            "and click yes. No password.\n"
                                            "Ctrl+N new chat  ·  Ctrl + / − text size  ·  Esc stop"))
            self.list.append(self._quick_actions())
        for ev in chat.events:
            if ev["type"] in ("user", "assistant", "note"):
                self.list.append(Bubble(ev["type"], ev["text"]))
            elif ev["type"] == "tool":
                c = ToolCard(ev["name"], ev["shown"]); c.add_output(ev.get("output", ""))
                c.finish(tools.ToolResult(ev.get("output", ""), ev.get("ok", True)))
                self.list.append(c)
            elif ev["type"] == "line":
                lab = Gtk.Label(label=ev["text"], xalign=0, wrap=True, selectable=True); lab.add_css_class("dim")
                self.list.append(lab)
        self.set_title(f"Eclipse AI — {chat.title}" if chat.messages else "Eclipse AI")
        self._scroll_down(force=True)

    def _scroll_down(self, force: bool = False):
        adj = self.scroller.get_vadjustment()
        if not force and not getattr(self, "stick", True):
            return
        def go():
            adj.set_value(adj.get_upper() - adj.get_page_size()); self.stick = True; return False
        GLib.timeout_add(30, go)

    def _on_scrolled(self, adj):
        self.stick = (adj.get_upper() - adj.get_value() - adj.get_page_size()) < 60

    # ----- model server -----
    def _boot_server(self):
        if not self.client.is_up():
            if not shutil.which("ollama"):
                GLib.idle_add(self.show_setup, "engine")
                return
            GLib.idle_add(self.status.set_text, "starting the AI engine…")
            try:
                subprocess.run(["systemctl", "--user", "--no-ask-password", "start", config.OLLAMA_UNIT],
                               capture_output=True, timeout=60)
                self.started_server = True
            except Exception:
                pass
            t0 = time.monotonic()
            while time.monotonic() - t0 < 30 and not self.client.is_up():
                time.sleep(0.5)
        if self.client.is_up():
            GLib.idle_add(self._after_server_up)
        elif self.cfg["model"] == ultra.MODEL_ID and ultra.available():
            GLib.idle_add(self._fill_models, [])
            GLib.idle_add(lambda: self.status.set_text(f"ready · {self.alias(self.cfg['model'])}") and False)
        else:
            GLib.idle_add(self.show_setup, "server")

    def _after_server_up(self):
        models = self.client.models()
        local = [m for m in models if m != ultra.MODEL_ID]
        if not local and not (self.cfg["model"] == ultra.MODEL_ID and ultra.available()):
            self.show_setup("model")
            return False
        self._fill_models(models)
        if self.stack.get_visible_child_name() == "setup":
            self.stack.set_visible_child_name("chat")
        self.status.set_text(f"ready · {self.alias(self.cfg['model'])}")
        # warm the model so the first answer is quick (Totality needs no warm-up)
        if self.cfg["model"] != ultra.MODEL_ID:
            warm = json.dumps({"model": self.cfg["model"], "keep_alive": self.cfg.get("keep_alive", "15m"),
                               "options": {"num_ctx": int(self.cfg.get("num_ctx", 8192))}})
            threading.Thread(target=lambda: subprocess.run(
                ["curl", "-s", "-m", "600", "-o", "/dev/null", f"{self.cfg['host']}/api/generate", "-d", warm],
                capture_output=True, stdin=subprocess.DEVNULL), daemon=True).start()
        return False

    def shutdown(self):
        """Stop whatever is running (timed run, reply, download) so no child process is left behind."""
        if self.run:
            self.run.stop()
            if self.run_thread:
                self.run_thread.join(4)   # let the running command be killed and the report be written
        if self.agent:
            self.agent.cancel()
        if self.pulling:
            self.pulling.cancel()

    def _on_close(self, *_):
        self.shutdown()
        try:
            self.cfg["window"] = [self.get_width(), self.get_height()]; config.save(self.cfg)
        except Exception:
            pass
        return False

    def stop_server_if_ours(self):
        """Free the RAM: stop the model server unit if this window started it (the unit's own idle
        watchdog covers every other case; a system-wide ollama.service is never touched)."""
        if self.started_server:
            subprocess.run(["systemctl", "--user", "--no-ask-password", "stop", config.OLLAMA_UNIT], capture_output=True,
                           timeout=60)
            self.started_server = False

    # ----- sending -----
    def _entry_key(self, ctrl, keyval, keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (state & Gdk.ModifierType.SHIFT_MASK):
            self.send(); return True
        return False

    def send(self, text: str | None = None):
        if self.busy:
            return
        if not self.check_enabled():
            return
        buf = self.entry.get_buffer()
        if text is None:
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
        if not text:
            return
        buf.set_text("")
        seconds = self.DURATIONS[self.dur_dd.get_selected()][1]
        m = re.match(r"^/work\s+(\S+)\s+(.+)$", text, re.S)
        if m:
            try:
                seconds = parse_duration(m.group(1)); text = m.group(2).strip()
            except ValueError as e:
                self.status.set_text(str(e)); buf.set_text(text); return
        if seconds:
            self.start_run(text, seconds); return
        if not self.chat.messages:
            self.chat.title = text[:60]
            self._clear_list()   # drop the welcome and quick actions
        self.chat.messages.append({"role": "user", "content": text})
        self.chat.events.append({"type": "user", "text": text})
        self.list.append(Bubble("user", text))
        self.set_title(f"Eclipse AI — {self.chat.title}")
        self._set_busy(True)
        self.current = Bubble("assistant"); self.current_ev = None
        self.list.append(self.current); self._scroll_down(force=True)
        self.agent = Agent(self.cfg)
        ctx = tools.ToolContext(approve=self._approve)
        ctx.note = self._note
        self.ctx = ctx
        threading.Thread(target=self._worker, args=(ctx,), daemon=True).start()

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.send_btn.set_visible(not busy); self.stop_btn.set_visible(busy)
        self.entry.set_sensitive(not busy)
        if not busy:
            self.entry.grab_focus()

    def stop(self):
        if self.run and self.busy:
            self.run.stop(); self.status.set_text("stopping the run…"); return
        if self.ctx and self.busy:
            self.ctx.cancelled = True
        if self.agent and self.busy:
            self.agent.cancel()
        if self.busy:
            self.status.set_text("stopping…")

    # ----- callbacks used by both a normal reply and a timed run (called on the worker thread) -----
    def on_text(self, delta):
        GLib.idle_add(self._on_text, delta)

    def on_tool_start(self, name, shown, args):
        ev = threading.Event(); holder = {}
        chat = self.chat
        def make():
            card = ToolCard(name, shown); self.list.append(card); holder["card"] = card
            chat.events.append({"type": "tool", "name": name, "shown": shown, "output": "", "ok": True})
            holder["ev"] = chat.events[-1]
            self._scroll_down(); ev.set(); return False
        GLib.idle_add(make); ev.wait()
        return holder

    def on_tool_done(self, holder, delta, result):
        def apply():
            if delta is not None:
                holder["card"].add_output(delta); holder["ev"]["output"] += delta
            if result is not None:
                holder["card"].finish(result); holder["ev"]["ok"] = result.ok
                if not holder["ev"]["output"]:
                    holder["ev"]["output"] = result.text
                # a finished tool means the next text is a fresh bubble
                self.current = Bubble("assistant"); self.current_ev = None; self.list.append(self.current)
            self._scroll_down(); return False
        GLib.idle_add(apply)

    def on_status(self, s):
        if self.run:
            return   # the run strip has priority
        GLib.idle_add(self.status.set_text, s)

    def on_note(self, text):
        self._note(text)

    def on_run_status(self, st):
        def show():
            if self.run:
                self.runstrip.show_status(st)
                self.status.set_text("")
            return False
        GLib.idle_add(show)

    def _worker(self, ctx):
        try:
            self.agent.run(self.chat, ctx, self.on_text, self.on_tool_start, self.on_tool_done, self.on_status)
        finally:
            GLib.idle_add(self._finished)

    # ----- timed autonomous run -----
    def start_run(self, goal: str, seconds: int):
        if self.busy:
            return
        if not self.chat.messages:
            self.chat.title = f"⏱ {goal[:56]}"
            self._clear_list()
        shown = f"Work for {plain_time(seconds)} on: {goal}"
        self.chat.messages.append({"role": "user", "content": f"[timed run, {fmt(seconds)}] {goal}"})
        self.chat.events.append({"type": "user", "text": shown})
        self.list.append(Bubble("user", shown))
        self.set_title(f"Eclipse AI — {self.chat.title}")
        self._set_busy(True)
        self.stop_btn.set_tooltip_text("Stop the run (Esc)")
        self.current = Bubble("assistant"); self.current_ev = None
        self.list.append(self.current); self._scroll_down(force=True)
        self.run = Run(self.cfg, goal, seconds, self)
        self.runstrip.show_status(self.run.status())
        self.run_thread = threading.Thread(target=self._run_worker, daemon=True)
        self.run_thread.start()

    def _run_worker(self):
        run = self.run
        try:
            run.start()
        finally:
            summary = run.summary_for_chat()
            def done():
                self.chat.messages.append({"role": "assistant", "content": summary})
                self.chat.events.append({"type": "assistant", "text": summary})
                self.list.append(Bubble("assistant", summary))
                self.run = None
                self.runstrip.set_visible(False)
                self.status.set_text({"finished": "run finished early", "timeout": "run: time is up",
                                      "stopped": "run stopped"}.get(run.outcome, f"run {run.outcome}"))
                self._finished()
                if elevate.queue_split()[0]:
                    self.run_root_queue()   # card: "Run N root commands now?"
                return False
            GLib.idle_add(done)

    def open_runs(self):
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._spawn(["xdg-open", str(RUNS_DIR)])

    def run_root_queue(self):
        """Card "Run N root commands now?"; yes = one root batch through arclightd. Lines that work leave
        the root review script, failed ones stay. Used after a timed run and from the menu."""
        if self.busy:
            self.status.set_text("busy: try again when this reply or run is done"); return
        if config.load().get("root_mode", "ask") == "queue":
            self.status.set_text(f'root_mode is "queue": run {rootq.SCRIPT} yourself'); return
        cmds, rest = elevate.queue_split()
        if not cmds:
            self.status.set_text("nothing in the root queue can run as one batch" if rest else
                                 "nothing is waiting for root right now"); return
        if not elevate.available():
            self.status.set_text("the Eclipse root service (arclightd) is not running"); return
        self._set_busy(True)
        self.current = Bubble("assistant"); self.current_ev = None
        self.list.append(self.current); self._scroll_down(force=True)
        ctx = tools.ToolContext(approve=self._approve)
        ctx.note = self._note
        self.ctx = ctx

        def work():
            try:
                card = self.on_tool_start("root_queue", f"root queue: {len(cmds)} command{'s' if len(cmds) != 1 else ''}", {})
                ctx.on_output = lambda s: self.on_tool_done(card, s, None)
                r = elevate.run_queue(ctx, confirm=True)
                self.on_tool_done(card, None, r)
                lines = r.text.strip().splitlines()
                last = next((l for l in lines if "done and removed" in l), lines[0] if lines else "")
                if last:
                    self._note(("✔ " if r.ok else "⏸ ") + last)
            except Exception as e:
                self._note(f"✖ root queue failed: {e}")
            finally:
                GLib.idle_add(self._finished)
        threading.Thread(target=work, daemon=True).start()

    def show_root_queue(self):
        if rootq.SCRIPT.exists():
            self._spawn(["xdg-open", str(rootq.SCRIPT)])
            self.status.set_text(rootq.summary())
        else:
            self.status.set_text("nothing is waiting for root right now")

    def _on_text(self, delta):
        if not self.current.text and delta.strip() == "":
            return False
        self.current.append_text(delta)
        if self.current_ev is None:
            self.current_ev = {"type": "assistant", "text": ""}; self.chat.events.append(self.current_ev)
        self.current_ev["text"] = self.current.text
        self._scroll_down(); return False

    def _note(self, text: str):
        def add():
            lab = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True); lab.add_css_class("dim")
            self.list.append(lab); self.chat.events.append({"type": "line", "text": text}); self._scroll_down(); return False
        GLib.idle_add(add)

    def _finished(self):
        if not self.is_active():
            last = next((e["text"] for e in reversed(self.chat.events) if e["type"] == "assistant"), "Done.")
            self._spawn(["notify-send", "-a", "Eclipse AI", "-i", "arclight", "Eclipse AI", last[:160]])
        child = self.list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            if isinstance(child, Bubble) and child.role == "assistant" and not child.text.strip():
                self.list.remove(child)
            child = nxt
        self.chat.save(); self._rebuild_history_menu(); self._set_busy(False); self.agent = None; self.ctx = None
        self._scroll_down(); return False

    # called on the worker thread
    def _approve(self, approval: tools.Approval) -> tools.Approval:
        ev = threading.Event(); holder = {}
        def show():
            card = ApprovalCard(approval, lambda _c: ev.set()); holder["card"] = card
            self.list.append(card); self._scroll_down(); return False
        GLib.idle_add(show); ev.wait()
        def swap():
            self.list.remove(holder["card"]); return False
        GLib.idle_add(swap)
        return approval


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=config.APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        config.ensure_dirs()
        self.import_note = ""
        try:
            self.import_note = config.import_arch_ai()
        except Exception:
            pass
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        style.install()

    def do_shutdown(self):
        if self.win:
            self.win.stop_server_if_ours()
        Gtk.Application.do_shutdown(self)

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        self.activate()
        if args and args[0] == "--send" and len(args) > 1:
            GLib.timeout_add(1500, lambda: self.win.send(" ".join(args[1:])) or False)
        elif "--work-for" in args:
            i = args.index("--work-for")
            try:
                seconds = parse_duration(args[i + 1])
                goal = " ".join(a for a in args[:i] + args[i + 2:] if a != "--gui").strip()
                if goal:
                    GLib.timeout_add(1500, lambda: self.win.start_run(goal, seconds) or False)
            except (IndexError, ValueError) as e:
                print(f"eclipse-ai: {e}", file=sys.stderr)
        return 0

    def do_activate(self):
        if not self.win:
            self.win = Window(self, getattr(self, "import_note", ""))
        self.win.present()
        # Hyprland does not focus on activate by default; ask it directly.
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            subprocess.Popen(["bash", "-c", f"hyprctl dispatch 'hl.dsp.focus({{ window = \"class:^({config.APP_ID})$\" }})' "
                                            ">/dev/null 2>&1"])


def main():
    app = App()

    def on_signal(*_):
        # Ctrl+C / SIGTERM (e.g. logout): stop any run, stop the model server we started, then leave.
        if app.win:
            app.win.shutdown()
            app.win.stop_server_if_ours()
        app.quit()
        GLib.timeout_add(1500, lambda: os._exit(0))
        return True
    import signal
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, on_signal)
    return app.run(sys.argv)
