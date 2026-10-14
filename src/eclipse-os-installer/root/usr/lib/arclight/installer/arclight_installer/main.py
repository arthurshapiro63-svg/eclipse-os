"""arclight-install: install Eclipse OS (codename Arclight; the name is chosen during the install).

  arclight-install                       interactive: Quick or Advanced (the Rite)
  arclight-install --config plan.json    non-interactive (tests, scripted installs)
  arclight-install --plan-only           build and print a plan without installing
  arclight-install --export-bundle DIR   (from the OLD system) write a verified migration bundle
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import disks, ui
from .engine import Engine, InstallError, RUN

GiB = 1024 ** 3


def gib(n):
    return f"{n / GiB:.0f} GiB" if n >= 10 * GiB else f"{n / GiB:.1f} GiB"


def online():
    return subprocess.run(["bash", "-c", "getent hosts archlinux.org >/dev/null 2>&1"], timeout=10).returncode == 0


def hash_password(pw):
    p = subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=pw, capture_output=True, text=True)
    if p.returncode != 0:
        raise InstallError("could not hash the password")
    return p.stdout.strip()


def old_shadow_hash(partition, user, subdir=""):
    """Read the old system's password hash for `user` (read-only mount) so the same password keeps working."""
    mnt = RUN / "shadow-probe"
    mnt.mkdir(parents=True, exist_ok=True)
    fstype = subprocess.run(["blkid", "-o", "value", "-s", "TYPE", partition], capture_output=True, text=True).stdout.strip()
    if subprocess.run(["mount", "-o", disks.old_mount_opts(fstype), partition, str(mnt)], capture_output=True).returncode != 0:
        return None
    try:
        sh = mnt / subdir / "etc/shadow"
        for line in sh.read_text().splitlines():
            f = line.split(":")
            if f[0] == user and f[1] and not f[1].startswith(("!", "*")):
                return f[1]
    except OSError:
        return None
    finally:
        subprocess.run(["umount", str(mnt)], capture_output=True)
    return None


def v_hostname(s):
    return None if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", s) else "letters, digits and dashes only"


def v_user(s):
    return None if re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", s) else "lowercase letters, digits, - and _"


def v_osname(s):
    from arclight import identity
    return None if identity.valid_name(s) else "1-40 letters, digits, spaces, dots, dashes"


# ---------------------------------------------------------------- quick install

def targets(scan):
    opts = []
    for d in scan:
        esp = next((p for p in d["parts"] if p.get("esp")), None)
        for p in d["parts"]:
            o = p.get("os")
            if o and disks.uefi() and esp and p["fstype"] in ("ext4", "btrfs", "xfs") and o["free"] >= 25 * GiB:
                opts.append(("side", {"mode": "side-by-side", "disk": d["path"], "partition": p["path"], "esp": esp["path"],
                                      "os": o, "fstype": p["fstype"]},
                             f"Next to {o['name']} on {p['path']}: keeps it untouched ({gib(o['free'])} free)"))
        if d["free_regions"]:
            big = max(r[2] for r in d["free_regions"])
            if big >= 30 * GiB:
                opts.append(("free", {"mode": "free", "disk": d["path"], "esp": esp["path"] if esp else None},
                             f"Free space on {d['path']} ({gib(big)} unpartitioned)"))
        label = f"{d['model'] or 'disk'} {gib(d['size'])}"
        osn = ", ".join(sorted({p['os']['name'] for p in d['parts'] if p.get('os')}))
        opts.append(("erase", {"mode": "erase", "disk": d["path"]},
                     f"Erase {d['path']} ({label}){': deletes ' + osn if osn else (' (empty)' if d['empty'] else ': deletes everything on it')}"))
    return opts


def quick():
    ui.header("Quick install", "Your desktop, your apps, your files. A few questions, then it builds itself.")
    scan = ui.spin("looking at your disks (read-only)", disks.scan)
    opts = targets(scan)
    if not opts:
        ui.say("No usable disk found (need 16 GiB or more).", ui.RED)
        return 1
    key = ui.choose(f"Where should {ui.os_name()} go?", [(str(i), o[2]) for i, o in enumerate(opts)])
    t = dict(opts[int(key)][1])
    cfg = {"mode": t["mode"], "disk": t.get("disk"), "fingerprint": True}
    old = t.get("os")
    if t["mode"] == "side-by-side":
        cfg.update(partition=t["partition"], esp=t["esp"], old_os_name=old["name"], old_root_subdir=old.get("root_subdir", ""))
        ui.note(f"{old['name']} stays exactly as it is. {ui.os_name()} gets its own folder (/arclight) on that disk and its own")
        ui.note("boot entry; the switch happens in one step at the very end, after everything is checked.")
    elif t["mode"] == "free":
        cfg["esp"] = t.get("esp")
    # OS name (asked here too; the advanced install makes you choose it)
    cfg["os_name"] = ui.ask("Name of the operating system", ui.os_name(), validate=v_osname,
                            hint="shown in the boot menu, login screen and system info")
    cfg["hostname"] = ui.ask("Machine name", (old or {}).get("hostname") or "arclight", validate=v_hostname)
    # user + migration
    old_users = (old or {}).get("users", [])
    migrate = {"enabled": False}
    if old_users:
        if len(old_users) == 1:
            ou = old_users[0]
        else:
            k = ui.choose("Whose files should come over?", [(u["name"], f"{u['name']} ({u['home']})") for u in old_users])
            ou = next(u for u in old_users if u["name"] == k)
        if ui.confirm(f"Bring over {ou['home']} (settings, projects, files)? Nothing is moved: it is copied or shared."):
            migrate = {"enabled": True, "old_user": ou, "from_home": ou["home"]}
    uname = ui.ask("User name", migrate.get("old_user", {}).get("name") or "", validate=v_user)
    user = {"name": uname, "autologin": True, "full_name": (migrate.get("old_user", {}).get("gecos") or uname.title()).split(",")[0]}
    if migrate["enabled"] and ui.confirm("Keep your existing password?"):
        h = old_shadow_hash(t["partition"], migrate["old_user"]["name"], old.get("root_subdir", ""))
        if h:
            user["password_hash"] = h
        else:
            ui.note("could not read the old password; please choose one")
    if "password_hash" not in user:
        while True:
            p1 = ui.ask("Password", password=True)
            p2 = ui.ask("Password again", password=True)
            if p1 and p1 == p2:
                user["password_hash"] = hash_password(p1)
                break
            ui.say("  the two passwords differ (or are empty)", ui.RED)
    cfg["user"] = user
    cfg["timezone"] = (old or {}).get("timezone") or "America/New_York"
    cfg["locale"] = (old or {}).get("locale") or "en_US.UTF-8"
    cfg["keymap"] = (old or {}).get("keymap") or "us"
    if migrate["enabled"]:
        from arclight.migrate import plan as mplan
        mnt = RUN / "plan-probe"
        mnt.mkdir(parents=True, exist_ok=True)
        subprocess.run(["mount", "-o", disks.old_mount_opts(t["fstype"]), t["partition"], str(mnt)], check=True)
        try:
            try:
                src = disks.old_home_in(mnt, t["partition"], t["fstype"], old.get("root_subdir", ""),
                                        migrate["old_user"]["home"])
            except disks.LayoutError as e:
                raise SystemExit(f"Your files cannot be brought over automatically: {e}")
            ui.say("Measuring your home folder (this can take a few minutes for big homes)…", ui.MUTED)
            sysb = int(subprocess.run(["du", "-sxB1", "/run/archiso/airootfs"], capture_output=True, text=True).stdout.split()[0] or 0)
            plan = mplan.build(src, f"/home/{uname}", max(0, old["free"] - sysb), can_share=True)
            ui.note(f"(the new system itself takes {gib(sysb)}; that is already subtracted)")
        finally:
            subprocess.run(["umount", str(mnt)])
        while True:
            ui.say(plan.summary(), ui.BRIGHT if plan.fits() else ui.RED)
            for i in sorted(plan.items, key=lambda i: -i.bytes)[:14]:
                ui.note(f"   {i.action:<5} {gib(i.bytes):>9}  ~/{i.path}  {i.reason}")
            a = ui.choose("Migration plan", [("ok", "Looks right"), ("share", "Choose what to SHARE (no copy)"),
                                             ("skip", "Choose what to SKIP"), ("all", "Show every item")],
                          default="ok" if plan.fits() else "share")
            if a == "ok":
                if plan.fits():
                    break
                ui.say("It does not fit yet: share or skip more.", ui.RED)
            elif a == "all":
                for i in sorted(plan.items, key=lambda i: -i.bytes):
                    print(f"   {i.action:<5} {gib(i.bytes):>9}  ~/{i.path}")
            else:
                big = [i for i in sorted(plan.items, key=lambda i: -i.bytes) if i.bytes > 50 * 1024 ** 2][:40]
                sel = ui.choose_many(f"Items to {a.upper()}", [(i.path, f"{gib(i.bytes):>9}  ~/{i.path}") for i in big],
                                     selected=[i.path for i in big if i.action == a])
                for i in big:
                    if i.path in sel:
                        i.action, i.reason = a, "your choice"
                    elif i.action == a:
                        i.action, i.reason = "copy", "your choice"
        migrate["plan"] = json.loads(plan.to_json())
        cfg["packages"] = {"from_old_system": True, "online": online()}
    else:
        cfg["packages"] = {"from_old_system": False, "online": online()}
    cfg["migrate"] = migrate
    # two choices, both changeable later in Settings
    from arclight.edition import has_ai
    cfg["ai"] = has_ai() and ui.confirm("Use the AI features? (Ask, Eclipse AI, Fix with AI. You can change this later)", True)
    cfg["eclipse_look"] = ui.choose("Look", [("eclipse", "Eclipse: the eclipse theme, wallpaper and boot animation"),
                                             ("plain", "Plain: neutral graphite, same features")],
                                    default="eclipse") == "eclipse"
    # summary
    ui.header("Ready", "Nothing has been written yet.")
    lines = [f"Where      {t['mode']}: {t.get('partition') or t.get('disk')}",
             f"OS name    {cfg['os_name']}", f"Machine    {cfg['hostname']}", f"User       {uname} (autologin on tty1, like now)",
             f"Time       {cfg['timezone']} · {cfg['locale']} · keyboard {cfg['keymap']}",
             f"Migration  {'yes: ' + migrate['old_user']['home'] if migrate['enabled'] else 'no (fresh desktop)'}",
             (f"AI         {'on' if cfg['ai'] else 'off'} · look: {'Eclipse' if cfg['eclipse_look'] else 'plain'}" if has_ai()
              else f"Look       {'Eclipse' if cfg['eclipse_look'] else 'plain'} (Claude Code ready, no built-in AI)"),
             f"Packages   desktop from this USB" + (" + your full list from the old system (online)" if cfg["packages"].get("from_old_system") else "")]
    for l in lines:
        ui.say("  " + l)
    if t["mode"] == "erase":
        ui.say(f"\n  This ERASES {t['disk']}.", ui.RED)
        typed = ui.ask(f"Type {t['disk']} to confirm")
        if typed != t["disk"]:
            ui.say("Not confirmed. Nothing was changed.")
            return 1
        cfg["confirm_disk"] = t["disk"]
    elif not ui.confirm("Install now?"):
        ui.say("Cancelled. Nothing was changed.")
        return 1
    return run(cfg)


def run(cfg, dry=False):
    RUN.mkdir(parents=True, exist_ok=True)
    safe = {k: v for k, v in cfg.items() if k != "user"} | {"user": {k: ("***" if "pass" in k else v) for k, v in cfg["user"].items()}}
    (RUN / "plan.json").write_text(json.dumps(safe, indent=2))
    if dry:
        print(json.dumps(safe, indent=2))
        return 0
    eng = Engine(cfg, ui=ui.Progress())
    try:
        rep = eng.run()
    except Exception as e:
        ui.header("Install stopped", str(e))
        if not eng.committed:
            ui.say("Nothing changed on your existing system: the boot order is as it was, and the files this run")
            ui.say("created were removed. Log: /var/log/arclight-install.log")
        return 2
    ui.header(f"{cfg['os_name']} is installed", "It is now the default. Your previous system is still in the boot menu.")
    if rep.get("old_system_untouched"):
        ui.say(f"  Old system verified unchanged ({rep['old_system_entries']} files checked).", ui.OK)
    if rep.get("migration"):
        ui.say(f"  Migration: {rep['migration']['summary']}")
    for w in rep.get("warnings", []):
        ui.say(f"  note: {w}", ui.WARN)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="arclight-install", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)
    try:
        if a.config:
            cfg = json.loads(Path(a.config).read_text())
            if cfg.get("user", {}).pop("keep_old_password", False):
                ou = cfg.get("migrate", {}).get("old_user", {}).get("name") or cfg["user"]["name"]
                h = old_shadow_hash(cfg["partition"], ou, cfg.get("old_root_subdir", ""))
                if not h:
                    raise SystemExit("could not read the old password hash")
                cfg["user"]["password_hash"] = h
            if "password" in cfg.get("user", {}) and "password_hash" not in cfg["user"]:
                cfg["user"]["password_hash"] = hash_password(cfg["user"].pop("password"))
            return run(cfg, dry=a.plan_only)
        ui.logo()
        mode = ui.choose("How do you want to install?", [
            ("quick", "Quick: my desktop and apps, ready in minutes"),
            ("rite", "Advanced: the Rite (build every part by hand; harder than Arch)"),
            ("shell", "Just give me a shell")])
        if mode == "quick":
            return quick()
        if mode == "rite":
            from . import rite
            return rite.begin()
        return 0
    except KeyboardInterrupt:
        print("\ncancelled; nothing was changed")
        return 130
