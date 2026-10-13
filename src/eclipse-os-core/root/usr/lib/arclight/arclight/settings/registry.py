"""The settings registry: one typed list of every setting on the machine.

The AI (arc set / MCP), the CLI and the Arclight Settings app all go through this, so
a change made by any of them applies live, persists, and shows up everywhere.

    reg = Registry()
    reg.get("appearance.gaps_out")        -> 10
    reg.set("appearance.gaps_out", 14)    -> applied live + persisted
    reg.list("appearance")                -> [{key, type, value, description, ...}]

Sources:
  hypr.*        every Hyprland option, generated from the API stubs Hyprland ships
  appearance.*, wallpaper.*, input.*, display.*, audio.*, power.*, network.*, bluetooth.*,
  idle.*, shell.*, ai.*, system.* : curated, friendly settings (see curated.py)
"""
import json
import os
import re
import threading
from pathlib import Path

from ..rpc import RPCError
from ..util import user_config_dir, atomic_write


class Setting:
    def __init__(self, key, type, description, getter, setter=None, choices=None, min=None, max=None, unit=None,
                 scope="user", group=None, alias_of=None, live=True, choices_fn=None):
        self.key, self.type, self.description = key, type, description
        self.getter, self.setter = getter, setter
        self._choices, self.choices_fn = choices, choices_fn
        self.min, self.max, self.unit = min, max, unit
        self.scope, self.group = scope, group or key.split(".")[0]
        self.alias_of, self.live = alias_of, live

    @property
    def choices(self):
        if self.choices_fn:
            try:
                return self.choices_fn()
            except Exception:
                return self._choices
        return self._choices

    def coerce(self, v):
        t = self.type
        if t == "bool":
            if isinstance(v, str):
                lv = v.strip().lower()
                if lv in ("1", "true", "yes", "on", "enable", "enabled"):
                    return True
                if lv in ("0", "false", "no", "off", "disable", "disabled"):
                    return False
                raise RPCError(f"{self.key}: expected true/false, got {v!r}")
            return bool(v)
        if t == "int":
            try:
                v = int(float(v))
            except (TypeError, ValueError):
                raise RPCError(f"{self.key}: expected an integer, got {v!r}")
        elif t == "float":
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise RPCError(f"{self.key}: expected a number, got {v!r}")
        elif t == "color":
            s = str(v).strip()
            if re.fullmatch(r"#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", s):
                v = "#" + s.lstrip("#").upper()
            elif not re.fullmatch(r"rgba?\([^)]*\)", s):
                raise RPCError(f"{self.key}: expected a colour like #3DA9FF, got {v!r}")
        elif t == "enum":
            ch = self.choices or []
            if ch and str(v) not in [str(c) for c in ch]:
                raise RPCError(f"{self.key}: must be one of {', '.join(map(str, ch))}")
            v = str(v)
        elif t in ("string", "path", "gradient", "gap", "raw"):
            v = v if isinstance(v, (int, float)) and t == "gap" else str(v)
        if t in ("int", "float"):
            if self.min is not None and v < self.min:
                raise RPCError(f"{self.key}: minimum is {self.min}")
            if self.max is not None and v > self.max:
                raise RPCError(f"{self.key}: maximum is {self.max}")
        return v

    def describe(self, with_value=True):
        d = {"key": self.key, "type": self.type, "description": self.description, "scope": self.scope,
             "group": self.group, "writable": self.setter is not None}
        for k in ("choices", "min", "max", "unit", "alias_of"):
            v = getattr(self, k)
            if v not in (None, []):
                d[k] = v
        if with_value:
            try:
                d["value"] = self.getter()
            except Exception as e:
                d["value"] = None
                d["error"] = str(e)[:200]
        return d


class Store:
    """~/.config/arclight/settings.json: persisted values for settings Arclight owns."""

    def __init__(self, path=None):
        self.path = Path(path or user_config_dir() / "settings.json")
        self.lock = threading.Lock()

    def load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self, key, default=None):
        return self.load().get(key, default)

    def put(self, key, value):
        with self.lock:
            d = self.load()
            if value is None:
                d.pop(key, None)
            else:
                d[key] = value
            atomic_write(self.path, json.dumps(d, indent=2, sort_keys=True) + "\n")


class Registry:
    def __init__(self, store=None, system_client=None):
        self.store = store or Store()
        self.system_client = system_client
        self._settings = {}
        self._lock = threading.RLock()
        from . import hypr_provider, curated
        hypr_provider.register(self)
        curated.register(self)

    def add(self, s):
        self._settings[s.key] = s

    def has(self, key):
        return key in self._settings

    def _find(self, key):
        s = self._settings.get(key)
        if s:
            return s
        close = [k for k in self._settings if key in k][:8]
        raise RPCError(f"unknown setting {key!r}" + (f"; did you mean: {', '.join(close)}" if close else
                                                       "; use settings search"))

    def get(self, key):
        return self._find(key).getter()

    def set(self, key, value):
        s = self._find(key)
        if not s.setter:
            raise RPCError(f"{key} is read-only")
        v = s.coerce(value)
        with self._lock:
            s.setter(v)
        try:
            now = s.getter()
        except Exception:
            now = v
        return {"key": key, "value": now, "requested": v, "applied_live": s.live}

    def describe(self, key):
        return self._find(key).describe()

    def list(self, prefix=None, with_values=True, include_hypr=False):
        out = []
        for k in sorted(self._settings):
            if prefix and not k.startswith(prefix):
                continue
            if not prefix and not include_hypr and k.startswith("hypr."):
                continue
            out.append(self._settings[k].describe(with_value=with_values))
        return out

    def groups(self):
        g = {}
        for s in self._settings.values():
            g[s.group] = g.get(s.group, 0) + 1
        return g

    def search(self, text, limit=40):
        words = text.lower().split()
        scored = []
        for s in self._settings.values():
            hay = f"{s.key} {s.description}".lower()
            score = sum(3 if w in s.key.lower() else 1 for w in words if w in hay)
            if score and all(w in hay for w in words[:1]):
                if not s.key.startswith("hypr."):
                    score += 2  # prefer the friendly curated keys
                scored.append((score, s))
        scored.sort(key=lambda t: (-t[0], t[1].key))
        return [s.describe() for _, s in scored[:limit]]

    def reset(self, key, live=True):
        """Drop a persisted override so the hand-written config value wins again (live: reloads Hyprland)."""
        s = self._find(key)
        target = s.alias_of or key
        self.store.put(target, None)
        if target.startswith("hypr."):
            from . import hypr_provider
            hypr_provider.write_lua(self.store)
            if live:
                import subprocess
                r = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    return {"key": key, "reset": True, "value": self.get(key)}
        return {"key": key, "reset": True, "note": "the hand-written config value applies after `hyprctl reload`"}
