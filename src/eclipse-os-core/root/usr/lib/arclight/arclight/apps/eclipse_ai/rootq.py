"""Root review queue: root commands that were not run right away (from Arch AI by Arthur).

They are appended to one script at a fixed path: during timed runs (nobody is watching), with
root_mode "queue", when arclightd is not reachable, and for mixed commands that cannot run as one
root batch. The user can read it and run it themselves, or run the eligible lines as one batch through
arclightd (elevate.run_queue: the card after a timed run, the menu item or `eclipse-ai --run-root-queue`);
lines that succeed are then removed. Nothing here ever calls sudo.
"""
import re
import time
from pathlib import Path

from . import config

SCRIPT = config.DATA_DIR / "root-review.sh"

HEADER = """#!/usr/bin/env bash
# Eclipse AI root review script (made by Eclipse AI).
# Every command below needed root and was not run right away (timed run, mixed command, ...).
# Read it and delete what you do not want. Then either let Eclipse AI run the plain `sudo` lines
# (menu -> "Run root queue now", or `eclipse-ai --run-root-queue`; one password prompt, lines that work are
# removed), or run it yourself, e.g.:   arc root bash ~/.local/share/eclipse-ai/root-review.sh
# Delete this file (or `eclipse-ai --clear-root-queue`) once you are done.
set -u
"""


def _read() -> str:
    try:
        return SCRIPT.read_text()
    except FileNotFoundError:
        return ""


def pending() -> list[str]:
    """Queued commands (non-comment, non-empty lines after the header)."""
    return [l for l in _read().splitlines()
            if l.strip() and not l.startswith("#") and l.strip() != "set -u"]


def add(command: str, why: str = "", run_id: str = "") -> tuple[int, bool]:
    """Append one command. Returns (line number, added). added=False when it was already queued."""
    command = command.strip()
    text = _read()
    if not text:
        SCRIPT.parent.mkdir(parents=True, exist_ok=True)
        text = HEADER
    if command in pending():
        lines = text.splitlines()
        return lines.index(command) + 1, False
    stamp = time.strftime("%Y-%m-%d %H:%M")
    note = f"# [{stamp}]" + (f" run {run_id}" if run_id else "") + (f": {why}" if why else "")
    text = text.rstrip("\n") + "\n" + note + "\n" + command + "\n"
    SCRIPT.write_text(text)
    SCRIPT.chmod(0o700)
    return len(text.splitlines()), True


def remove(commands: list[str]) -> int:
    """Drop these queued command lines (and the '# [stamp]' note right above each).
    Everything else, including hand-written comments, stays. Returns how many were removed."""
    targets = set(commands)
    lines = _read().splitlines()
    drop = set()
    for i, l in enumerate(lines):
        if l in targets and not l.startswith("#"):
            drop.add(i)
            if i and lines[i - 1].startswith("# ["):
                drop.add(i - 1)
    if not drop:
        return 0
    SCRIPT.write_text("\n".join(l for i, l in enumerate(lines) if i not in drop) + "\n")
    return len([i for i in drop if lines[i] in targets])


def clear() -> None:
    SCRIPT.unlink(missing_ok=True)


def summary() -> str:
    """One line for the end of a run or a reply."""
    n = len(pending())
    if not n:
        return ""
    return f"{n} command{'s' if n != 1 else ''} need{'s' if n == 1 else ''} root and {'is' if n == 1 else 'are'} waiting for your review in {SCRIPT}"


def strip_sudo(command: str) -> str:
    """'sudo pacman -S x' -> 'pacman -S x' (used only for display / dedupe)."""
    return re.sub(r"(^|[\s;&|(])sudo(\s+-\S+)*\s+", r"\1", command)
