"""Which Eclipse OS edition this is, set when the ISO is built (tools/build-iso.sh EDITION=core|ai):

  core  "Eclipse OS": no built-in AI features (no Ask, no Eclipse AI, no AI buttons, no routines,
        no Fix-with-AI, no local models). Claude Code is installed and the whole machine is still
        open to it: arclightd, arclight-session, the MCP server and `arc` are all there.
  ai    "Eclipse OS AI": everything, including the built-in AI features.

The edition lives in /etc/arclight/edition. A missing file means "ai" (a development tree, or an
install made before editions existed)."""
import os
from pathlib import Path

FILE = Path("/etc/arclight/edition")
NAMES = {"core": "Eclipse OS", "ai": "Eclipse OS AI"}


def edition():
    forced = os.environ.get("ARCLIGHT_EDITION", "").strip().lower()   # tests / previews
    if forced in NAMES:
        return forced
    try:
        e = FILE.read_text().strip().lower()
    except OSError:
        return "ai"
    return e if e in NAMES else "ai"


def has_ai():
    """True when the built-in AI features exist in this edition (the user can still switch them off)."""
    return edition() == "ai"
