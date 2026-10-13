"""Machine-level settings: identity, time, locale, kernel, sysctl, users, power, overview."""
import json
import os
import pwd
import grp
import re
import socket
import time
from pathlib import Path

from ..rpc import RPCError
from ..util import run, run_full, which, atomic_write

ENV = {"LANG": "C", "LC_ALL": "C"}


# ---------------------------------------------------------------- overview

def _meminfo():
    m = {}
    for l in Path("/proc/meminfo").read_text().splitlines():
        k, v = l.split(":", 1)
        m[k] = int(v.split()[0]) * 1024
    return m


def _temps():
    out = {}
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            name = (hw / "name").read_text().strip()
            for t in hw.glob("temp*_input"):
                label_f = hw / t.name.replace("_input", "_label")
                label = label_f.read_text().strip() if label_f.exists() else t.name
                out[f"{name}/{label}"] = int(t.read_text()) / 1000
        except OSError:
            continue
    return out


def _battery():
    bats = []
    for b in Path("/sys/class/power_supply").glob("*"):
        try:
            if (b / "type").read_text().strip() == "Battery":
                bats.append({"name": b.name, "capacity": int((b / "capacity").read_text()),
                             "status": (b / "status").read_text().strip()})
        except OSError:
            continue
    return bats


def info():
    """One-call overview of the whole machine: identity, load, memory, disks, GPU, network, health."""
    osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', Path("/etc/os-release").read_text(), re.M))
    rel = Path("/etc/arclight/release")
    mem = _meminfo()
    up = float(Path("/proc/uptime").read_text().split()[0])
    disks = []
    for line in run(["df", "-B1", "--output=source,fstype,size,used,avail,target", "-x", "tmpfs", "-x", "devtmpfs",
                     "-x", "efivarfs", "-x", "overlay", "-x", "squashfs"], check=False).splitlines()[1:]:
        p = line.split()
        if len(p) >= 6:
            disks.append({"source": p[0], "fstype": p[1], "size": int(p[2]), "used": int(p[3]), "free": int(p[4]),
                          "mount": " ".join(p[5:])})
    nets = []
    try:
        for i in json.loads(run(["ip", "-j", "addr"], check=False) or "[]"):
            if i.get("ifname") == "lo":
                continue
            nets.append({"if": i["ifname"], "state": i.get("operstate"),
                         "addrs": [f"{a['local']}/{a['prefixlen']}" for a in i.get("addr_info", [])]})
    except Exception:
        pass
    failed = [l.split()[0] for l in run(["systemctl", "--failed", "--no-legend", "--plain"], check=False).splitlines() if l.strip()]
    cpu = re.search(r"model name\s*:\s*(.*)", Path("/proc/cpuinfo").read_text())
    root_fs = run(["findmnt", "-no", "FSTYPE", "/"], check=False).strip()
    return {
        "hostname": socket.gethostname(),
        "os": osr.get("PRETTY_NAME"),
        "name": osr.get("NAME"),
        "arclight": rel.read_text().strip() if rel.exists() else None,
        "kernel": os.uname().release,
        "uptime_s": int(up),
        "load": os.getloadavg(),
        "cpu": {"model": cpu.group(1) if cpu else None, "threads": os.cpu_count()},
        "memory": {"total": mem.get("MemTotal"), "available": mem.get("MemAvailable"),
                   "swap_total": mem.get("SwapTotal"), "swap_free": mem.get("SwapFree")},
        "gpu": [l for l in run("lspci | grep -Ei 'vga|3d|display'", check=False).splitlines()],
        "temps_c": _temps(),
        "battery": _battery(),
        "disks": disks,
        "root_fs": root_fs,
        "network": nets,
        "failed_units": failed,
        "users_logged_in": [l.split()[1] for l in run(["loginctl", "list-sessions", "--no-legend"], check=False).splitlines() if len(l.split()) > 1],
        "firmware": "uefi" if Path("/sys/firmware/efi").exists() else "bios",
        "boot": run(["cat", "/proc/cmdline"], check=False).strip(),
    }


# ---------------------------------------------------------------- identity / time / locale

def hostname(name=None):
    """Get, or set (when `name` is given), the machine name."""
    if name:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", name):
            raise RPCError("hostname: letters, digits and dashes, 1-63 chars, not starting with a dash")
        run(["hostnamectl", "set-hostname", name])
        hosts = Path("/etc/hosts")
        text = hosts.read_text() if hosts.exists() else ""
        line = f"127.0.1.1\t{name}.localdomain\t{name}"
        if re.search(r"^127\.0\.1\.1\s.*$", text, re.M):
            text = re.sub(r"^127\.0\.1\.1\s.*$", line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
        atomic_write(hosts, text)
    return {"hostname": socket.gethostname(), "static": Path("/etc/hostname").read_text().strip() if Path("/etc/hostname").exists() else None}


def timezone(tz=None, ntp=None):
    """Get or set the timezone (e.g. 'America/New_York') and NTP sync."""
    if tz:
        if not Path("/usr/share/zoneinfo", tz).is_file():
            raise RPCError(f"unknown timezone {tz!r}")
        run(["timedatectl", "set-timezone", tz])
    if ntp is not None:
        run(["timedatectl", "set-ntp", "true" if ntp else "false"])
    d = {}
    for l in run(["timedatectl", "show"], env=ENV).splitlines():
        k, _, v = l.partition("=")
        d[k] = v
    return d


def timezones(query=None):
    """List timezone names (filtered)."""
    tz = run(["timedatectl", "list-timezones"], env=ENV).split()
    return [t for t in tz if not query or query.lower() in t.lower()]


def locale(lang=None, keymap=None, x11_layout=None):
    """Get or set the system locale (LANG), console keymap and default X11/Wayland layout."""
    if lang:
        gen = Path("/etc/locale.gen")
        text = gen.read_text()
        entry = f"{lang} UTF-8" if lang.endswith("UTF-8") else lang
        if not re.search(rf"^{re.escape(entry)}", text, re.M):
            if re.search(rf"^#\s*{re.escape(entry)}", text, re.M):
                text = re.sub(rf"^#\s*({re.escape(entry)})", r"\1", text, flags=re.M)
            else:
                text += f"\n{entry}\n"
            atomic_write(gen, text)
            run(["locale-gen"], timeout=600)
        run(["localectl", "set-locale", f"LANG={lang}"])
    if keymap:
        run(["localectl", "set-keymap", "--no-convert", keymap])
    if x11_layout:
        run(["localectl", "set-x11-keymap", "--no-convert", x11_layout])
    d = {}
    for l in run(["localectl", "status"], env=ENV).splitlines():
        if ":" in l:
            k, v = l.split(":", 1)
            d[k.strip()] = v.strip()
    return d


# ---------------------------------------------------------------- kernel

def _bootloader():
    if Path("/etc/kernel/cmdline").exists() or Path("/boot/EFI/Linux").exists() and any(Path("/boot/EFI/Linux").glob("*.efi")):
        return "uki"
    if Path("/boot/grub/grub.cfg").exists() and Path("/etc/default/grub").exists():
        return "grub"
    if Path("/boot/loader/entries").exists():
        return "systemd-boot"
    return "unknown"


def cmdline(set_to=None, add=None, remove=None):
    """Get the kernel command line; or change it persistently (add/remove params, or replace)
    for GRUB (/etc/default/grub), UKI (/etc/kernel/cmdline) or systemd-boot entries."""
    current = Path("/proc/cmdline").read_text().strip()
    bl = _bootloader()
    if not (set_to or add or remove):
        return {"running": current, "bootloader": bl, "configured": _configured_cmdline(bl)}
    conf = _configured_cmdline(bl)
    params = conf.split() if conf else []
    if set_to is not None:
        params = set_to.split()
    for a in (add.split() if isinstance(add, str) else add or []):
        key = a.split("=")[0]
        params = [p for p in params if p.split("=")[0] != key] + [a]
    for r in (remove.split() if isinstance(remove, str) else remove or []):
        params = [p for p in params if p != r and p.split("=")[0] != r]
    new = " ".join(params)
    if bl == "grub":
        f = Path("/etc/default/grub")
        text = f.read_text()
        text = re.sub(r'^GRUB_CMDLINE_LINUX_DEFAULT=.*$', f'GRUB_CMDLINE_LINUX_DEFAULT="{new}"', text, flags=re.M)
        atomic_write(f, text)
        out = run(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], timeout=300)
    elif bl == "uki":
        atomic_write(Path("/etc/kernel/cmdline"), new + "\n")
        out = run(["mkinitcpio", "-P"], timeout=900)
    elif bl == "systemd-boot":
        out = ""
        for e in Path("/boot/loader/entries").glob("*.conf"):
            text = e.read_text()
            text = re.sub(r"^options .*$", f"options {new}", text, flags=re.M)
            atomic_write(e, text)
    else:
        raise RPCError("cannot tell which boot loader is in use")
    return {"bootloader": bl, "configured": new, "note": "takes effect after a reboot", "output": out[-2000:]}


def _configured_cmdline(bl):
    if bl == "grub":
        m = re.search(r'^GRUB_CMDLINE_LINUX_DEFAULT="(.*)"', Path("/etc/default/grub").read_text(), re.M)
        return m.group(1) if m else ""
    if bl == "uki":
        f = Path("/etc/kernel/cmdline")
        return f.read_text().strip() if f.exists() else ""
    if bl == "systemd-boot":
        for e in sorted(Path("/boot/loader/entries").glob("*.conf")):
            m = re.search(r"^options (.*)$", e.read_text(), re.M)
            if m:
                return m.group(1)
    return ""


SYSCTL_FILE = Path("/etc/sysctl.d/90-arclight.conf")


def sysctl(key=None, value=None, persist=True):
    """Read a kernel tunable (or all matching a prefix), or set it live and persistently."""
    if key and value is not None:
        run(["sysctl", "-w", f"{key}={value}"])
        if persist:
            lines = SYSCTL_FILE.read_text().splitlines() if SYSCTL_FILE.exists() else ["# managed by arclightd"]
            lines = [l for l in lines if not l.split("=")[0].strip() == key] + [f"{key} = {value}"]
            atomic_write(SYSCTL_FILE, "\n".join(lines) + "\n")
        return {key: run(["sysctl", "-n", key]).strip(), "persisted": persist}
    out = run(["sysctl", "-a"], check=False, env=ENV)
    d = {}
    for l in out.splitlines():
        k, _, v = l.partition(" = ")
        if not key or k.startswith(key):
            d[k] = v
    return d


# ---------------------------------------------------------------- users

def users():
    """Regular users with their groups and shells."""
    out = []
    for pw in pwd.getpwall():
        if 1000 <= pw.pw_uid < 60000 or pw.pw_uid == 0:
            groups = [g.gr_name for g in grp.getgrall() if pw.pw_name in g.gr_mem]
            out.append({"name": pw.pw_name, "uid": pw.pw_uid, "home": pw.pw_dir, "shell": pw.pw_shell, "groups": groups})
    return out


def user_add(name, groups=None, shell="/bin/bash", password=None, admin=False):
    """Create a user (admin=true adds wheel + arclight)."""
    g = list(groups or [])
    if admin:
        g += ["wheel", "arclight"]
    cmd = ["useradd", "-m", "-s", shell]
    if g:
        cmd += ["-G", ",".join(sorted(set(g)))]
    run(cmd + [name])
    if password:
        run(["chpasswd"], input=f"{name}:{password}\n")
    return [u for u in users() if u["name"] == name][0]


def user_mod(name, add_groups=None, remove_groups=None, shell=None, password=None):
    """Change a user's groups, shell or password."""
    for g in add_groups or []:
        run(["gpasswd", "-a", name, g])
    for g in remove_groups or []:
        run(["gpasswd", "-d", name, g])
    if shell:
        run(["usermod", "-s", shell, name])
    if password:
        run(["chpasswd"], input=f"{name}:{password}\n")
    return [u for u in users() if u["name"] == name][0]


def user_del(name, remove_home=False):
    """Delete a user (home kept unless remove_home=true)."""
    run(["userdel"] + (["-r"] if remove_home else []) + [name])
    return {"deleted": name}


# ---------------------------------------------------------------- power

def power(action):
    """reboot | poweroff | suspend | hibernate | logout-all."""
    acts = {"reboot": ["systemctl", "reboot"], "poweroff": ["systemctl", "poweroff"],
            "suspend": ["systemctl", "suspend"], "hibernate": ["systemctl", "hibernate"]}
    if action not in acts:
        raise RPCError(f"action must be one of {', '.join(acts)}")
    # Reply first, act a moment later, so the caller sees the answer.
    run(["systemd-run", "--on-active=2", "--timer-property=AccuracySec=100ms"] + acts[action])
    return {"scheduled": action, "in_seconds": 2}


def exec_(cmd, cwd=None, env=None, timeout=600, input=None, as_user=None):
    """Run any command as root (or as_user). `cmd` is a shell string or an argv list."""
    if as_user:
        if isinstance(cmd, str):
            cmd = ["runuser", "-u", as_user, "--", "bash", "-lc", cmd]
        else:
            cmd = ["runuser", "-u", as_user, "--"] + list(cmd)
    r = run_full(cmd, timeout=int(timeout), input=input, env=env, cwd=cwd)
    return r


def register(api):
    api.method("sys.info")(info)
    api.method("sys.hostname")(hostname)
    api.method("sys.timezone")(timezone)
    api.method("sys.timezones")(timezones)
    api.method("sys.locale")(locale)
    api.method("sys.cmdline")(cmdline)
    api.method("sys.sysctl")(sysctl)
    api.method("sys.users")(users)
    api.method("sys.user_add")(user_add)
    api.method("sys.user_mod")(user_mod)
    api.method("sys.user_del")(user_del)
    api.method("sys.power")(power)
    api.method("exec")(exec_)
