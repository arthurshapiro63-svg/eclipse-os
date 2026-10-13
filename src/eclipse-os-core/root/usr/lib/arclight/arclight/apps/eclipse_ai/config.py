"""Paths and user config for Eclipse AI (based on Arch AI by Arthur).

Config: ~/.config/eclipse-ai/config.json. Chats, logs, timed runs and the root review script:
~/.local/share/eclipse-ai/. On the first start Arch AI's chats and its model choice are COPIED over
(never moved): ~/.local/share/arch-ai and ~/.config/arch-ai stay exactly as they are.
"""
import json
import os
import shutil
from pathlib import Path

APP_ID = os.environ.get("ECLIPSE_AI_APP_ID", "dev.arclight.EclipseAI")   # override only to test a second window
APP_NAME = "Eclipse AI"
HOME = Path.home()
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "eclipse-ai"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "eclipse-ai"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "eclipse-ai"
LOG_DIR = DATA_DIR / "log"
CHAT_DIR = DATA_DIR / "chats"
RUNS_DIR = DATA_DIR / "runs"
CONFIG_FILE = CONFIG_DIR / "config.json"
OLLAMA_UNIT = "eclipse-ai-ollama.service"
BACKUP_SUFFIX = ".eclipse-ai.bak"
# Arch AI on a migrated home (read only, copied from)
ARCH_DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "arch-ai"
ARCH_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "arch-ai" / "config.json"

# Eclipse names in the window instead of real model names (same idea as Arch AI's Arch names):
# Crescent = the quick everyday model, Diamond Ring = the stronger one, Corona = the biggest local one,
# Totality = the strongest (cloud-backed, shown only by this name).
MODEL_NAMES = {"qwen3.5:9b": "Eclipse Crescent", "gemma4:12b": "Eclipse Diamond Ring",
               "gpt-oss:20b": "Eclipse Corona", "ultra": "Eclipse Totality"}

DEFAULTS = {
    # Swap the model here (or from the picker in the window). Anything `ollama pull`-ed works.
    "model": "qwen3.5:9b",
    "host": "http://127.0.0.1:11434",
    # "auto" = off for models that allow it, "low" for gpt-oss. Or true/false/"low"/"medium"/"high".
    "think": "auto",
    "num_ctx": 8192,
    "temperature": 0.3,
    "keep_alive": "15m",
    "command_timeout": 120,
    "max_tool_rounds": 8,
    "font_size": 11,          # pt; Ctrl+plus / Ctrl+minus in the app
    "window": [980, 720],     # remembered on close
    # "ask": root commands run through arclightd after a yes in the window (no password).
    # "queue": never run root, only add it to the root review script.
    "root_mode": "ask",
    # the model the "Get the AI model" button downloads on a machine without one
    "starter_model": "qwen3.5:9b",
    "starter_size_gb": 6.6,
    "model_names": dict(MODEL_NAMES),
}


def display_name(cfg: dict, model: str, index: int = 0) -> str:
    names = dict(MODEL_NAMES)
    names.update(cfg.get("model_names") or {})
    if model in names:
        return names[model]
    if model == "ultra":
        return "Eclipse Totality"
    return "Eclipse Penumbra" if index == 0 else f"Eclipse Penumbra {index + 1}"


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text()))
    except FileNotFoundError:
        save(cfg)
    except Exception:
        pass
    # Arch names never show up here, even from an imported config
    cfg["model_names"] = {k: v for k, v in (cfg.get("model_names") or {}).items() if not str(v).startswith("Arch")}
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    tmp.replace(CONFIG_FILE)


def ensure_dirs() -> None:
    for d in (DATA_DIR, LOG_DIR, CHAT_DIR, CONFIG_DIR, RUNS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)


KEEP_FROM_ARCH = ("model", "think", "num_ctx", "temperature", "keep_alive", "command_timeout", "max_tool_rounds",
                  "font_size", "window")


def import_arch_ai() -> str:
    """First start on a migrated home: COPY Arch AI's chats and settings (never move or change them).
    Runs once (a marker file); cheap (a few small JSON files). Returns a short note, or ""."""
    marker = DATA_DIR / ".arch-ai-imported"
    if marker.exists():
        return ""
    ensure_dirs()
    n = 0
    src = ARCH_DATA / "chats"
    if src.is_dir():
        for f in src.glob("*.json"):
            dst = CHAT_DIR / f.name
            if not dst.exists():
                try:
                    shutil.copy2(f, dst)
                    n += 1
                except OSError:
                    pass
    took = []
    if ARCH_CONFIG.exists() and not CONFIG_FILE.exists():
        try:
            old = json.loads(ARCH_CONFIG.read_text())
            cfg = dict(DEFAULTS)
            for k in KEEP_FROM_ARCH:
                if k in old:
                    cfg[k] = old[k]
            save(cfg)
            took.append("settings")
        except (OSError, ValueError):
            pass
    marker.write_text("copied from ~/.local/share/arch-ai (the originals are untouched)\n")
    if n:
        took.insert(0, f"{n} chat{'s' if n != 1 else ''}")
    return ("Brought over from Arch AI: " + " and ".join(took) + ". Arch AI itself is untouched.") if took else ""


def models_dir() -> Path:
    """Where the model server keeps models: Arthur's Arch AI models when a migrated home has them
    (shared, never moved), else Eclipse AI's own folder."""
    arch = ARCH_DATA / "models"
    if (arch / "manifests").is_dir():
        return arch
    return DATA_DIR / "models"


# ---------------------------------------------------------------- the global AI switch
def ai_enabled() -> bool:
    """Settings -> AI: `ai.enabled` (another part of Eclipse may add it). Read defensively: the session
    daemon first, then its settings file, default on."""
    if os.environ.get("ECLIPSE_AI_FORCE_OFF") == "1":
        return False
    try:
        from arclight.edition import has_ai
        if not has_ai():
            return False
    except ImportError:
        pass
    try:
        from arclight import client as C
        v = C.call("settings.get", key="ai.enabled")
        v = v.get("value") if isinstance(v, dict) else v
        if v is not None:
            return _truthy(v)
    except Exception:
        pass
    try:
        f = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "arclight" / "settings.json"
        d = json.loads(f.read_text())
        if "ai.enabled" in d:
            return _truthy(d["ai.enabled"])
    except (OSError, ValueError, TypeError):
        pass
    return True


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "off", "no", "")
    return bool(v)
