"""Is the AI switched on? (Settings → AI → "Use the AI features", or the choice made at install.)
Every AI entry point (Ask, Eclipse AI, Fix-with-AI, routines, the intro's AI scenes) checks this."""

from .edition import has_ai

OFF_TEXT = "The AI features are off. Turn them on in Settings → AI."
CORE_TEXT = "This edition has no built-in AI. Claude Code can still run the whole PC: open a terminal and type claude."


def ai_enabled():
    if not has_ai():
        return False
    try:
        from .settings.registry import Store
        return Store().get("ai.enabled", True) is not False
    except Exception:
        return True


def off_text():
    return OFF_TEXT if has_ai() else CORE_TEXT


def notify_off(app="Eclipse OS"):
    import subprocess
    title = "AI is off" if has_ai() else "No built-in AI"
    subprocess.run(["notify-send", "-a", app, "-i", "arclight", title, off_text()], capture_output=True)
