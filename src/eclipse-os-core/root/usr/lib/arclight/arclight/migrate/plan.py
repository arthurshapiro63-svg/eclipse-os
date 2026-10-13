"""Migration plan: decide, per top-level item of a home directory, whether to COPY it into the
new system, SHARE it (bind the original in place: nothing moved, nothing duplicated) or SKIP it
(caches, trash: things that regenerate). Sizes are measured, so the plan can be checked
against the free space before a single byte is written.
"""
import json
import os
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path

GiB = 1024 ** 3

# never worth copying: they regenerate
SKIP = {".cache", ".local/share/Trash", ".npm/_cacache", ".gradle/caches", ".cargo/registry", ".thumbnails",
        ".local/share/baloo", ".var/app/*/cache"}
# containers whose children are judged one by one (so Steam can be shared while the rest is copied)
SPLIT = {".local/share", ".local", "Projects", ".config"}
# big data that is fine to share between the old and new system rather than duplicate
SHARE_FIRST = (".local/share/Steam", "vms", ".local/share/arch-ai", ".ollama", ".local/share/bedrock-on-linux",
               "Unity", ".local/share/PrismLauncher", "Games", "minecraft-world-backups")


@dataclass
class Item:
    path: str
    bytes: int
    action: str = "copy"   # copy | share | skip
    reason: str = ""


@dataclass
class Plan:
    source_home: str
    target_home: str
    items: list = field(default_factory=list)
    free_bytes: int = 0
    reserve_bytes: int = 15 * GiB
    can_share: bool = True

    def total(self, action):
        return sum(i.bytes for i in self.items if i.action == action)

    def fits(self):
        return self.total("copy") + self.reserve_bytes <= self.free_bytes

    def to_json(self):
        return json.dumps({**asdict(self), "items": [asdict(i) for i in self.items]}, indent=1)

    @staticmethod
    def from_json(text):
        d = json.loads(text)
        d["items"] = [Item(**i) for i in d["items"]]
        return Plan(**d)

    def summary(self):
        h = lambda n: f"{n / GiB:.1f} GiB"
        return (f"copy {h(self.total('copy'))} · share {h(self.total('share'))} · skip {h(self.total('skip'))} · "
                f"free {h(self.free_bytes)} (keeping {h(self.reserve_bytes)} spare) · "
                f"{'fits' if self.fits() else 'DOES NOT FIT'}")


def du(path):
    try:
        out = subprocess.run(["du", "-sxB1", str(path)], capture_output=True, text=True, timeout=3600).stdout
        return int(out.split()[0]) if out else 0
    except Exception:
        return 0


def _children(home, rel):
    base = Path(home) / rel
    if not base.is_dir() or base.is_symlink():
        return None
    return sorted(str(p.relative_to(home)) for p in base.iterdir())


def build(source_home, target_home, free_bytes, can_share=True, reserve_bytes=15 * GiB, sizes=None, progress=None):
    """Classify every top-level home item (and children of the SPLIT containers)."""
    home = Path(source_home)
    items = []
    queue = sorted(str(p.relative_to(home)) for p in home.iterdir())
    while queue:
        rel = queue.pop(0)
        if rel in SPLIT:
            kids = _children(home, rel)
            if kids is not None:
                queue = kids + queue
                continue
        p = home / rel
        if progress:
            progress(rel)
        if p.is_symlink() or not p.is_dir():
            size = p.lstat().st_size if p.exists() or p.is_symlink() else 0
        else:
            size = (sizes or {}).get(rel) if sizes and rel in sizes else du(p)
        it = Item(rel, size)
        if rel in SKIP or any(rel.startswith(s.rstrip("*")) and "*" in s for s in SKIP):
            it.action, it.reason = "skip", "Cache or trash. It comes back by itself"
        items.append(it)
    plan = Plan(str(source_home), str(target_home), items, free_bytes, reserve_bytes, can_share)
    balance(plan)
    return plan


def balance(plan):
    """If the copy does not fit, share the big data dirs (largest of the preferred list first, then any
    other item over 4 GiB), until it fits. Without sharing, report that it cannot fit."""
    if plan.fits() or not plan.can_share:
        return plan
    by_path = {i.path: i for i in plan.items}
    for path in SHARE_FIRST:
        it = by_path.get(path)
        if it and it.action == "copy":
            it.action, it.reason = "share", "Big library. Both systems share it, so it is not copied twice"
            if plan.fits():
                return plan
    for it in sorted((i for i in plan.items if i.action == "copy"), key=lambda i: -i.bytes):
        if it.bytes < 4 * GiB:
            break
        it.action, it.reason = "share", "Big. Both systems share it, so everything fits"
        if plan.fits():
            return plan
    return plan
