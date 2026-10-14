"""Decide whether a shell command may run on its own or must be approved first.
(From Arch AI by Arthur. Eclipse: `arc root …` and `arclight-asroot …` count as root like sudo, a few
read-only `arc` commands run without asking, and the never-run list also covers Eclipse's own daemons.)

Rule of thumb: only a known read-only command runs automatically. Everything
else asks. Anything with sudo (and /etc, /boot writes) needs root: in chat it
asks, then runs as root through arclightd after the system password prompt (elevate.py);
otherwise it goes to the root review script.

In a timed autonomous run there is nobody to ask, so the run auto-approves
everything except `hard_block()` matches (things that could wreck the machine
or the home folder) and anything needing root (always queued, never elevated).
"""
import os
import re
import shlex
from pathlib import Path

# Commands that never change anything on disk (given the argument checks below).
ALWAYS_SAFE = {
    "ls", "eza", "exa", "tree", "cat", "bat", "head", "tail", "less", "more", "wc", "du", "df",
    "stat", "file", "free", "uptime", "uname", "hostname", "hostnamectl", "timedatectl", "localectl",
    "lscpu", "lsblk", "lspci", "lsusb", "lsmod", "lsof", "dmesg", "sensors", "nproc", "whoami", "id",
    "groups", "echo", "printf", "grep", "rg", "egrep", "fgrep", "sort", "uniq", "cut", "tr", "diff",
    "cmp", "md5sum", "sha256sum", "sha1sum", "basename", "dirname", "realpath", "readlink", "which",
    "whereis", "type", "command", "printenv", "locale", "fc-list", "fc-match", "glxinfo", "vulkaninfo",
    "jq", "column", "paste", "nl", "tac", "rev", "fold", "fmt", "strings", "hexdump", "od", "man",
    "pgrep", "pidof", "pstree", "ps", "ss", "dig", "host", "nslookup", "getent", "ldd", "namei",
    "getfacl", "lsattr", "mountpoint", "findmnt", "cal", "bc", "expr", "seq", "test", "[", "true",
    "false", "pwd", "cd", "date", "sleep", "xdg-open", "gtk-launch", "notify-send", "wl-paste",
    "wl-copy", "acpi", "upower", "cat", "wlr-randr", "xdg-mime", "xdg-user-dir", "env", "ping",
    "tput", "stty", "tty", "arch", "numfmt", "yes", "look", "comm", "join", "iostat", "vmstat",
    "mpstat", "sar", "nvtop", "radeontop", "uptime", "w", "who", "last", "lastlog", "loginctl",
    "pactl", "wpctl", "brightnessctl", "playerctl", "ollama", "flatpak", "pacman", "yay", "paru",
    "git", "systemctl", "journalctl", "hyprctl", "sed", "awk", "gawk", "find", "ip", "nmcli",
    "checkupdates", "pacman-conf", "pkg-config", "python", "python3", "xxd", "curl", "arc",
}

# Extra checks for commands that are only read-only with certain arguments.
def _args_ok(argv: list[str]) -> bool:
    cmd, args = argv[0], argv[1:]
    joined = " ".join(args)
    if cmd in ("pacman", "yay", "paru"):
        if not args:
            return False
        op = next((a for a in args if a.startswith("-")), "")
        return bool(re.match(r"^-(Q\w*|S[sil]\w*|F\w*|T|V|h|-query|-version|-help)$", op)) and not re.search(r"(^|\s)-\w*[wu]\w*", joined)
    if cmd == "git":
        return bool(args) and args[0] in {"status", "log", "diff", "show", "ls-files", "rev-parse", "describe",
                                          "blame", "shortlog", "remote", "--version", "branch", "tag", "stash", "config"} \
            and not re.search(r"(^|\s)(-d|-D|-m|-M|--delete|drop|pop|apply|push|add|remove|rename|set-url|--edit|--unset|--add)(\s|$)", joined) \
            and (args[0] not in ("stash", "config") or (len(args) > 1 and args[1] in ("list", "show", "--get", "--list", "-l", "--get-all")))
    if cmd == "systemctl":
        return any(a in {"status", "list-units", "list-unit-files", "is-active", "is-enabled", "is-failed", "show",
                         "cat", "list-timers", "list-sockets", "list-dependencies", "--version", "is-system-running"} for a in args) \
            and not re.search(r"(^|\s)(start|stop|restart|reload|enable|disable|mask|unmask|edit|set-|kill|daemon-reload|isolate|reboot|poweroff|suspend|hibernate)(\s|$)", joined)
    if cmd == "journalctl":
        return not re.search(r"--(vacuum|rotate|flush|relinquish|sync)", joined)
    if cmd == "hyprctl":
        return bool(args) and any(a in {"clients", "monitors", "workspaces", "activewindow", "activeworkspace", "devices", "binds",
                                        "version", "getoption", "layers", "splash", "cursorpos", "globalshortcuts", "instances",
                                        "animations", "configerrors", "rollinglog", "systeminfo", "decorations", "descriptions"} for a in args) \
            and not any(a in {"dispatch", "keyword", "reload", "setcursor", "kill", "notify", "output", "plugin", "seterror", "setprop", "switchxkblayout"} for a in args)
    if cmd == "sed":
        return not re.search(r"(^|\s)(-i|--in-place)", joined) and " w " not in joined
    if cmd in ("awk", "gawk"):
        return "system(" not in joined and ">" not in joined and "|" not in joined
    if cmd == "find":
        return not re.search(r"-(delete|exec|execdir|ok|okdir|fprint\w*)", joined)
    if cmd == "ip":
        return not re.search(r"(^|\s)(add|del|delete|set|flush|change|replace|link set|route add)(\s|$)", joined)
    if cmd == "nmcli":
        return not re.search(r"(^|\s)(connect|disconnect|up|down|modify|delete|add|set|reload|on|off|rescan)(\s|$)", joined)
    if cmd in ("pactl", "wpctl", "brightnessctl", "playerctl", "loginctl", "upower", "ollama", "flatpak"):
        return bool(args) and args[0] in {"list", "info", "stat", "status", "get-volume", "inspect", "get", "max", "metadata",
                                          "show-session", "list-sessions", "show-user", "-i", "-e", "-d", "--dump", "ps", "show",
                                          "search", "remotes", "--version", "-l", "list-units"}
    if cmd == "env":
        return not args
    if cmd == "sleep":
        return bool(args) and args[0].replace(".", "").isdigit() and float(args[0]) <= 30
    if cmd == "ping":
        return "-c" in args
    if cmd in ("python", "python3"):
        return args[:1] in (["--version"], ["-V"])
    if cmd == "xxd":
        return "-r" not in args
    if cmd == "curl":
        return not re.search(r"(^|\s)(-o|-O|--output|--remote-name|-T|--upload-file|-d|--data\w*|-F|--form|-X)(\s|$)", joined) and "|" not in joined
    if cmd == "man":
        return True
    if cmd == "arc":   # Eclipse's machine API: only the read-only corners run without asking
        if not args:
            return False
        if args[0] in ("doctor", "--help", "-h", "help", "version"):
            return True
        if args[0] == "settings" and len(args) > 1 and args[1] in ("get", "list", "search", "groups", "describe"):
            return True
        if args[0] in ("win", "windows", "ws", "mon", "screen", "apps") and len(args) > 1 and args[1] in ("list", "info", "active"):
            return True
        return False
    return True


SUDO_RE = re.compile(r"(^|[\s;&|(`])(sudo|doas|pkexec|su|sudo-rs|run0|machinectl|arclight-asroot|arc\s+root)(\s|$)")

# Never auto-approved, even in a timed run. Not a security boundary (the model runs as the user
# anyway); it catches the classic self-destruct commands.
HARD_BLOCK = [
    (re.compile(r"(^|[\s;&|(])rm\s+(-\w*[rR]\w*\s+)*(-\w+\s+)*(/|~|\$HOME|/home|/home/\w+|~/\.config|~/\.local|~/Projects|\.\.|\*)/?(\s|$|;|&)"), "deletes a whole top-level folder"),
    (re.compile(r"(^|[\s;&|(])(mkfs\S*|wipefs|fdisk|sfdisk|parted|cfdisk|gdisk)(\s|$)"), "touches disks or partitions"),
    (re.compile(r"(^|[\s;&|(])dd\s.*of=/dev/"), "writes to a block device"),
    (re.compile(r"(^|[\s;&|(])(reboot|shutdown|poweroff|halt|systemctl\s+(--\S+\s+)*(reboot|poweroff|halt|suspend|hibernate|kexec)|loginctl\s+(terminate|kill)-)"), "reboots, powers off or ends the session"),
    (re.compile(r"(^|[\s;&|(])(chmod|chown|chgrp)\s+(-\w*R\w*\s+)+\S+\s+(/|~|\$HOME|/home\S*)/?(\s|$)"), "changes permissions on a whole tree"),
    (re.compile(r"(^|[\s;&|(])(pkill|killall)\s+(-\S+\s+)*(Hyprland|hyprland|systemd|dbus-daemon|pipewire|wireplumber|kitty|ghostty|ollama|quickshell|qs|dms|arclightd|arclight-session)(\s|$)"), "kills the desktop session or the model server"),
    (re.compile(r":\(\)\s*\{.*:\|:.*\}"), "fork bomb"),
    (re.compile(r"(^|[\s;&|(])(shred|truncate)\s+.*(/dev/|/home|~)"), "shreds or truncates outside a project"),
    (re.compile(r"(^|[\s;&|(])(git)\s+(push\s+.*(--force|-f)\b|clean\s+.*-\w*x)"), "destructive git on a remote or untracked files"),
    (re.compile(r"(^|[\s;&|(])(curl|wget)\s.*\|\s*(ba|z|da)?sh(\s|$)"), "pipes a download into a shell"),
]


def hard_block(command: str) -> str | None:
    """Reason text if this command must never run unattended, else None."""
    for rx, why in HARD_BLOCK:
        if rx.search(command):
            return why
    return None


def needs_root(command: str) -> bool:
    return bool(SUDO_RE.search(command))


ROOT_ALIAS = re.compile(r"(^|[;&|(]\s*|\n\s*)(arc\s+root|arclight-asroot)(\s+)")


def normalize_root(command: str) -> str:
    """Eclipse's own root commands mean the same as plain sudo: `arc root X` / `arclight-asroot X` -> `sudo X`,
    so they take the same path (card in the window, then arclightd; queued in a timed run)."""
    return ROOT_ALIAS.sub(lambda m: m.group(1) + "sudo" + m.group(3), command.strip())


NOISE_REDIRECTS = re.compile(r"(2>&1|2>\s*/dev/null|&>\s*/dev/null|1?>\s*/dev/null|<\s*/dev/null)")


def classify(command: str) -> tuple[bool, list[str]]:
    """Return (auto_ok, reasons). auto_ok True means it may run without asking."""
    reasons: list[str] = []
    cmd = command.strip()
    if not cmd:
        return False, ["empty command"]
    if SUDO_RE.search(cmd):
        reasons.append("needs root (sudo)")
    if re.search(r"(^|[\s=:\"'])/(etc|boot)(/|\s|$|\"|')", cmd):
        reasons.append("touches /etc or /boot")
    stripped = NOISE_REDIRECTS.sub(" ", cmd)
    if re.search(r"[<>]", stripped):
        reasons.append("redirects to or from a file")
    if "$(" in cmd or "`" in cmd or "<(" in cmd or ">(" in cmd:
        reasons.append("uses command substitution")
    if re.search(r"(^|[^&])&([^&]|$)", stripped):
        reasons.append("runs in the background")
    if re.search(r"(^|[\s;&|(])(rm|rmdir|unlink|shred|dd|mkfs\S*|fdisk|parted|wipefs|truncate|chattr|mv|cp|ln|chmod|chown|chgrp|tee|install|rsync|kill|pkill|killall|reboot|shutdown|poweroff|halt|passwd|mount|umount|modprobe|rmmod)(\s|$)", stripped):
        reasons.append("can delete, overwrite or change files")
    if re.search(r"(^|[\s;&|(])(pacman|yay|paru)\s+-\w*[SRU]\w*", stripped) and not re.search(r"(^|[\s;&|(])(pacman|yay|paru)\s+-S[sil]\w*(\s|$)", stripped):
        reasons.append("installs or removes packages")
    etc_only = reasons == ["touches /etc or /boot"]
    if reasons and not etc_only:
        return False, reasons
    # Split into simple segments and make sure every one is a known read-only command.
    # (Reading a file under /etc with a read-only command is fine; changing it is not.)
    for seg in re.split(r"\|\||&&|\||;|\n", stripped):
        seg = seg.strip()
        if not seg:
            continue
        try:
            argv = shlex.split(seg)
        except ValueError:
            return False, ["could not parse the command"]
        if not argv:
            continue
        # skip leading VAR=value assignments
        while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
            argv = argv[1:]
        if not argv:
            continue
        name = os.path.basename(argv[0])
        if name not in ALWAYS_SAFE or not _args_ok([name] + argv[1:]):
            return False, reasons + [f"'{name}' is not on the read-only list"]
    return True, []


def expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path.strip()))).resolve()


def classify_write(path: str) -> tuple[bool, list[str]]:
    """File writes: creating a new file inside $HOME is fine; anything else asks."""
    p = expand(path)
    reasons = []
    s = str(p)
    if s.startswith("/etc") or s.startswith("/boot"):
        reasons.append("touches /etc or /boot")
    if p.exists():
        reasons.append("overwrites an existing file")
    home = str(Path.home())
    if not s.startswith(home + "/"):
        reasons.append("outside your home folder")
    return (not reasons), reasons
