"""arclight-watch: notices failing services and offers "Fix with AI" (user service); also turns Totality
(focus mode, was game mode) on while a game window is open (setting ai.auto_game_mode) and off when the
last one closes.

Polls failed units (system + user) every few seconds. A newly failed unit produces a
desktop notification with a "Fix with AI" action that opens the Ask overlay prefilled
with the request and the unit's recent log attached. With the setting ai.autofix the
agent starts on its own and reports back with a notification.
"""
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from arclight import identity

POLL = 8


def failed(user):
    cmd = ["systemctl"] + (["--user"] if user else []) + ["--failed", "--no-legend", "--plain", "--no-pager"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return set()
    return {l.split()[0] for l in out.splitlines() if l.strip()}


def unit_log(unit, user):
    cmd = ["journalctl"] + (["--user"] if user else []) + ["-u", unit, "-n", "80", "--no-pager", "-o", "short-iso"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except Exception as e:
        return f"(could not read log: {e})"


def setting(key, default):
    try:
        from arclight import client as C
        return C.call("settings.get", key=key)["value"]
    except Exception:
        return default


def record_event(unit, user):
    try:
        from arclight import client as C
        C.call("events.add", kind="unit-failed", message=f"{'user ' if user else ''}unit {unit} failed", unit=unit)
    except Exception:
        pass


def handle(unit, user):
    record_event(unit, user)
    if not setting("ai.notify_failures", True):
        return
    if not setting("ai.enabled", True):  # AI off: just say what failed, no Fix-with-AI
        subprocess.run(["notify-send", "-a", "Eclipse OS", "-i", "dialog-warning", f"{unit} failed",
                        "A service stopped working. Settings → System shows its log."], capture_output=True)
        return
    ctx = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "arclight" / f"failed-{unit}.log"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text(f"Unit: {unit} ({'user' if user else 'system'})\n\n" + unit_log(unit, user))
    request = (f"The {'user ' if user else ''}service {unit} just failed. Find out why from its log and fix it, "
               f"then confirm it is running (or explain why it should stay stopped).")
    if setting("ai.autofix", False):
        subprocess.Popen(["notify-send", "-a", identity.os_name(), "-i", "arclight", f"{unit} failed",
                          f"{identity.short_name()} is fixing it now…"])
        subprocess.Popen(["arclight-ask", "--cli", "--context", str(ctx), request],
                         stdout=open(ctx.with_suffix(".fix.log"), "w"), stderr=subprocess.STDOUT, start_new_session=True)
        return

    def ask():
        try:
            r = subprocess.run(["notify-send", "-a", identity.os_name(), "-i", "arclight", "-u", "critical", "-w",
                                "--action=fix=Fix with AI", "--action=log=Show log", f"{unit} failed",
                                "A service stopped working."], capture_output=True, text=True, timeout=3600)
        except subprocess.TimeoutExpired:
            return
        choice = r.stdout.strip()
        if choice == "fix":
            subprocess.Popen(["arclight-ask", "--prefill", request, "--context", str(ctx)], start_new_session=True)
        elif choice == "log":
            term = os.environ.get("TERMINAL", "ghostty")
            subprocess.Popen([term, "-e", "bash", "-c", f"less {ctx}"], start_new_session=True)

    threading.Thread(target=ask, daemon=True).start()


GAME_CLASS = re.compile(r"^(steam_app_\d+|gamescope|GeometryDash|Geometry Dash|Minecraft.*|minecraft.*)$")


def game_open():
    """Address of an open game window ('' = none)."""
    try:
        out = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True, timeout=5).stdout
        return next((c.get("address") or "x" for c in json.loads(out or "[]")
                     if GAME_CLASS.match(c.get("class") or "")), "")
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


class AutoGame:
    """Turns Totality on when a game appears; off when the last game closes, but only if it turned it on
    (a Totality you switched on by hand stays yours)."""

    def __init__(self):
        self.mine = False

    def tick(self):
        from arclight import client as C
        playing = game_open()
        try:
            if playing and not self.mine and setting("ai.auto_game_mode", True):
                st = C.call("totality.mode", action="status")
                self.mine = True  # first: a slow start must not make it look like nobody turned it on
                if not st.get("on"):
                    C.call("totality.mode", action="on", auto=True, window=playing)
                elif not st.get("auto"):
                    self.mine = False   # switched on by hand: it stays the user's
            elif not playing and self.mine:
                st = C.call("totality.mode", action="status")
                if st.get("on") and st.get("auto"):
                    C.call("totality.mode", action="off")
                self.mine = False
        except Exception:
            pass


def main():
    seen = {False: failed(False), True: failed(True)}  # already-failed units at start are not news
    auto = AutoGame()
    n = 0
    while True:
        time.sleep(2)  # games are noticed within ~2 s; failed units every POLL seconds
        auto.tick()
        n += 1
        if n % max(1, POLL // 2):
            continue
        for user in (False, True):
            now = failed(user)
            for unit in sorted(now - seen[user]):
                if not unit.startswith("arclight-totality"):  # its own safety net restores; not news
                    handle(unit, user)
            seen[user] = now
