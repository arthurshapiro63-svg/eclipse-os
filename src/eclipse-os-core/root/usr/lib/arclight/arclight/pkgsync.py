"""arclight-pkgsync: install the packages the installer could not (AUR ones, or everything when it was
offline). Runs as root at boot while /var/lib/arclight/pending-packages.txt is not empty; AUR packages
are built as the first regular user through yay (its pacman steps run through arclight-asroot with the job's token)."""
import json
import os
import pwd
import subprocess
import sys
import time
from pathlib import Path

from arclight import redact

PENDING = Path("/var/lib/arclight/pending-packages.txt")
LOG = Path("/var/log/arclight/pkgsync.log")


def log(msg):
    redact.append_private(LOG, f"[{time.strftime('%F %T')}] {redact.scrub_text(msg)}\n")
    print(msg, flush=True)


def online():
    return subprocess.run(["bash", "-c", "getent hosts archlinux.org >/dev/null && getent hosts aur.archlinux.org >/dev/null"]).returncode == 0


def first_user():
    for pw in sorted(pwd.getpwall(), key=lambda p: p.pw_uid):
        if 1000 <= pw.pw_uid < 60000:
            return pw
    return None


def main():
    sys.path.insert(0, "/usr/lib/arclight")
    from arclight.system import pkg
    if not PENDING.exists():
        return 0
    want = [l.strip() for l in PENDING.read_text().splitlines() if l.strip()]
    if not want:
        return 0
    for _ in range(60):
        if online():
            break
        time.sleep(5)
    else:
        log("offline; will try again next boot")
        return 0
    subprocess.run(["pacman", "-Sy", "--noconfirm"], capture_output=True)
    have = set(subprocess.run(["pacman", "-Qq"], capture_output=True, text=True).stdout.split())
    todo = [p for p in want if p not in have]
    user = first_user()
    done, failed = [], []
    for name in todo:  # one at a time: one broken AUR package must not block the rest
        try:
            pkg.install([name], aur=True, _peer={"uid": user.pw_uid if user else 0})
            done.append(name)
            log(f"installed {name}")
        except Exception as e:
            failed.append(name)
            log(f"FAILED {name}: {str(e)[:300]}")
    left = [p for p in want if p not in done and p not in have]
    PENDING.write_text("\n".join(left) + ("\n" if left else ""))
    rec = {"time": time.time(), "kind": "packages", "message": f"pkgsync: {len(done)} installed, {len(failed)} failed",
           "unit": "arclight-pkgsync.service", "data": {"installed": done, "failed": failed}}
    redact.append_private("/var/log/arclight/events.jsonl", json.dumps(rec) + "\n")
    log(rec["message"])
    return 0
