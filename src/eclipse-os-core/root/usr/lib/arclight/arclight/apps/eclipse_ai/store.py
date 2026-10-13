"""Chat history (JSON per chat) and the command log (based on Arch AI by Arthur)."""
import json
import time
import uuid
from pathlib import Path

from . import config


class Chat:
    def __init__(self, chat_id: str | None = None, title: str = "New chat"):
        self.id = chat_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.title = title
        self.created = time.time()
        self.updated = self.created
        self.messages: list[dict] = []   # ollama-style messages (system prompt is not stored)
        self.events: list[dict] = []     # what to draw: {"type": "user"/"assistant"/"tool"/"note", ...}

    @property
    def path(self) -> Path:
        return config.CHAT_DIR / f"{self.id}.json"

    def save(self) -> None:
        self.updated = time.time()
        config.CHAT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "id": self.id, "title": self.title, "created": self.created, "updated": self.updated,
            "messages": self.messages, "events": self.events,
        }, indent=1))
        tmp.replace(self.path)

    @classmethod
    def load(cls, path: Path) -> "Chat":
        d = json.loads(path.read_text())
        c = cls(d["id"], d.get("title", "Chat"))
        c.created, c.updated = d.get("created", 0), d.get("updated", 0)
        c.messages, c.events = d.get("messages", []), d.get("events", [])
        return c

    def delete(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def list_chats() -> list[dict]:
    """Newest first. Only reads the small header fields."""
    out = []
    for p in config.CHAT_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text())
            out.append({"id": d["id"], "title": d.get("title", "Chat"), "updated": d.get("updated", 0),
                        "path": p, "empty": not d.get("messages")})
        except Exception:
            continue
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def latest_chat() -> Chat | None:
    chats = list_chats()
    return Chat.load(chats[0]["path"]) if chats else None


def log_command(command: str, exit_code: int | None, output: str, kind: str = "shell") -> None:
    """Append one command + output to ~/.local/share/eclipse-ai/log/commands.log."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(config.LOG_DIR / "commands.log", "a") as f:
        f.write(f"[{stamp}] ({kind}) $ {command}\n")
        f.write(f"exit: {exit_code}\n")
        if output:
            f.write(output.rstrip("\n") + "\n")
        f.write("-" * 60 + "\n")
