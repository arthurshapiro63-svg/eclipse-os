"""arc: one command for the whole machine (the same API the AI uses).

  arc                              overview of the machine
  arc get KEY | arc set KEY VALUE  settings (arc settings [list|search|reset|groups])
  arc pkg search|info|install|remove|upgrade|updates|list|owns|files|history|orphans ...
  arc svc list|status|start|stop|restart|reload|enable|disable|mask|unmask UNIT [--user]
  arc log [UNIT] [--since 1h] [--prio err] [--grep X] [-n 100] [--user]   |  arc log errors
  arc file read|write|edit|ls|stat|rm|mkdir|cp|mv|chmod|history|revert ...
  arc root CMD...                  run a command as root (no password)
  arc screen shot [TARGET] [--grid] [-o FILE] | ocr | find TEXT | watch | pixel X Y
  arc input click X Y | move X Y | type TEXT | key CHORD | scroll N | drag X1 Y1 X2 Y2 | hold KEY MS
  arc win list|active|focus|close|float|tile|fullscreen|move|resize|to ...
  arc app list|launch|running      arc game list|launch|stop|mode [on|off|toggle|status]     arc ui tree|find|press|set-text
  arc totality [on|off|toggle|status]   focus mode (Super+G): the eclipse, everything else rests
  arc snap list|create|rollback|delete      arc sys hostname|timezone|locale|cmdline|users|reboot|poweroff
  arc history [-n 30] [--agent claude]      arc events      arc stop      arc ask "request"
  arc routine list|add NAME SCHEDULE PROMPT|remove|run|log ID   (AI requests on a schedule)
  arc update                       rebuild + install the OS itself (Arclight source) from ~/Projects/arclight
  arc doctor                       health check: what is wrong and the command that fixes it
  arc call METHOD key=value ...    raw API call (values are JSON when they parse)
  arc api [system|session]         list every API method

Add --json to any command for machine-readable output.
"""
import json
import os
import shlex
import subprocess
import sys
import time

from . import client as C
from .util import human

JSON = False


def out(v):
    if JSON or not isinstance(v, (dict, list, str)):
        print(json.dumps(v, indent=2, ensure_ascii=False, default=str))
    elif isinstance(v, str):
        print(v)
    else:
        print(json.dumps(v, indent=2, ensure_ascii=False, default=str))


def table(rows, cols, widths=None):
    if JSON:
        return out(rows)
    if not rows:
        print("(none)")
        return
    widths = widths or [max(len(str(c)), *(len(str(r.get(c, ""))[:60]) for r in rows)) for c in cols]
    print("  ".join(str(c).upper().ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("  ".join(str(r.get(c, "") if r.get(c) is not None else "")[:60].ljust(w) for c, w in zip(cols, widths)))


def kv(args):
    params = {}
    for a in args:
        if "=" not in a:
            raise SystemExit(f"expected key=value, got {a!r}")
        k, v = a.split("=", 1)
        try:
            params[k] = json.loads(v)
        except json.JSONDecodeError:
            params[k] = v
    return params


def flag(args, name, default=None, has_value=True):
    if name in args:
        i = args.index(name)
        if not has_value:
            del args[i]
            return True
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return default


def call(method, **kw):
    return C.call(method, **kw)


# ---------------------------------------------------------------- commands

def cmd_overview(args):
    i = call("sys.info")
    if JSON:
        return out(i)
    mem = i["memory"]
    print(f"{i['hostname']}  ·  {i.get('arclight') or i['os']}  ·  kernel {i['kernel']}  ·  up {i['uptime_s'] // 3600}h{i['uptime_s'] % 3600 // 60:02d}m")
    print(f"cpu   {i['cpu']['model']} ({i['cpu']['threads']} threads), load {', '.join(f'{x:.2f}' for x in i['load'])}")
    print(f"mem   {human(mem['total'] - mem['available'])} used of {human(mem['total'])}")
    for d in i["disks"]:
        print(f"disk  {d['mount']:<12} {human(d['used'])} / {human(d['size'])} ({d['fstype']})")
    for n in i["network"]:
        if n["addrs"]:
            print(f"net   {n['if']} {n['state']} {' '.join(n['addrs'])}")
    if i["failed_units"]:
        print(f"FAILED units: {', '.join(i['failed_units'])}   (arc log errors)")
    try:
        w = call("win.active")
        print(f"focus {w['class']} — {w['title'][:70]}" if w else "focus (none)")
    except C.Unavailable:
        print("session: not running (no Hyprland session)")


def cmd_get(args):
    r = call("settings.get", key=args[0])
    print(json.dumps(r["value"]) if not JSON else json.dumps(r, indent=2))


def cmd_set(args):
    if len(args) < 2:
        raise SystemExit("usage: arc set KEY VALUE")
    v = " ".join(args[1:])
    try:
        v = json.loads(v)
    except json.JSONDecodeError:
        pass
    r = call("settings.set", key=args[0], value=v)
    print(f"{r['key']} = {json.dumps(r['value'])}" if not JSON else json.dumps(r))


def cmd_settings(args):
    sub = args.pop(0) if args else "list"
    if sub == "list":
        rows = call("settings.list", prefix=args[0] if args else None)
        if JSON:
            return out(rows)
        for r in rows:
            v = json.dumps(r.get("value")) if "error" not in r else f"(error: {r['error'][:40]})"
            print(f"{r['key']:<32} {v[:40]:<40} {r['description'][:70]}")
    elif sub == "search":
        rows = call("settings.search", text=" ".join(args))
        for r in rows:
            print(f"{r['key']:<44} {json.dumps(r.get('value'))[:30]:<30} {r['description'][:60]}")
    elif sub == "reset":
        out(call("settings.reset", key=args[0]))
    elif sub == "groups":
        out(call("settings.groups"))
    elif sub == "get":
        cmd_get(args)
    elif sub == "set":
        cmd_set(args)
    else:
        out(call("settings.get", key=sub))


def cmd_pkg(args):
    sub = args.pop(0) if args else "list"
    aur = not flag(args, "--no-aur", False, has_value=False)
    if sub == "search":
        rows = call("pkg.search", query=" ".join(args), aur=aur)
        table([r for r in rows if "error" not in r], ["repo", "name", "version", "installed", "description"])
    elif sub == "info":
        out(call("pkg.info", name=args[0]))
    elif sub in ("install", "add"):
        r = call("pkg.install", names=args, aur=aur)
        out(r if JSON else {k: v for k, v in r.get("installed", {}).items()})
    elif sub in ("remove", "rm", "uninstall"):
        r = call("pkg.remove", names=args)
        print("removed:", " ".join(r["removed"]))
    elif sub == "upgrade":
        r = call("pkg.upgrade", aur=aur)
        print(r["output"][-3000:])
    elif sub == "updates":
        table(call("pkg.list", upgradable=True), ["name", "version", "new_version"])
    elif sub == "list":
        explicit = flag(args, "--explicit", False, has_value=False)
        foreign = flag(args, "--aur", False, has_value=False)
        table(call("pkg.list", explicit=explicit, foreign=foreign, query=args[0] if args else None), ["name", "version"])
    elif sub == "owns":
        out(call("pkg.owns", path=args[0]))
    elif sub == "files":
        print("\n".join(call("pkg.files", name=args[0])))
    elif sub == "history":
        table(call("pkg.history", lines=int(args[0]) if args else 40), ["time", "action", "name", "version"])
    elif sub == "orphans":
        print(" ".join(call("pkg.orphans")) or "(none)")
    elif sub == "refresh":
        print(call("pkg.refresh")["output"])
    else:
        raise SystemExit(f"unknown: arc pkg {sub}")


SVC_ACTIONS = ("start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask", "reenable", "kill", "reset-failed")


def cmd_svc(args):
    user = flag(args, "--user", False, has_value=False)
    sub = args.pop(0) if args else "list"
    if sub == "list":
        rows = C.call("svc.list", _user=user, query=args[0] if args else None, user=user)
        table(rows, ["unit", "active", "sub", "enabled", "description"])
    elif sub == "failed":
        table(C.call("svc.list", _user=user, state="failed", user=user), ["unit", "active", "sub", "description"])
    elif sub == "status":
        r = C.call("svc.status", _user=user, unit=args[0], user=user)
        if JSON:
            return out(r)
        p = r["properties"]
        print(f"{p.get('Id')}: {p.get('ActiveState')} ({p.get('SubState')}), enabled={p.get('UnitFileState')}, "
              f"pid={p.get('MainPID')}, result={p.get('Result')}")
        print("\n".join(r["recent_log"]))
    elif sub == "logs":
        cmd_log([args[0], "-n", args[1] if len(args) > 1 else "80"] + (["--user"] if user else []))
    elif sub in SVC_ACTIONS:
        r = C.call("svc.action", _user=user, unit=args[0], action=sub, user=user)
        print(f"{r['unit']}: {sub} -> {r['state']}")
    else:
        raise SystemExit(f"unknown: arc svc {sub}")


def cmd_log(args):
    user = flag(args, "--user", False, has_value=False)
    if args and args[0] == "errors":
        r = C.call("log.errors", _user=user, user=user)
        if JSON:
            return out(r)
        print("failed units:", ", ".join(r["failed_units"]) or "none")
        for g in r["error_sources"][:25]:
            print(f"\n[{g['count']}x] {g['source']}")
            for s in g["samples"]:
                print("   ", (s or "")[:200])
        if r["coredumps_7d"]:
            print("\ncoredumps (7d):", ", ".join(f"{c['exe']}" for c in r["coredumps_7d"]))
        return
    p = {"since": flag(args, "--since"), "priority": flag(args, "--prio"), "grep": flag(args, "--grep"),
         "lines": int(flag(args, "-n", 100)), "boot": flag(args, "--boot")}
    if flag(args, "-k", False, has_value=False):
        p["kernel"] = True
    if args:
        p["user_unit" if user else "unit"] = args[0]
    rows = C.call("log.query", _user=user, **{k: v for k, v in p.items() if v is not None})
    if JSON:
        return out(rows)
    for r in rows:
        print(f"{time.strftime('%m-%d %H:%M:%S', time.localtime(r['time']))} {(r['ident'] or r['unit'] or '?')[:22]:<22} "
              f"{'EWN'[min(2, max(0, r['prio'] - 2))] if r['prio'] <= 4 else ' '} {r['msg']}")


def cmd_file(args):
    sub = args.pop(0)
    if sub == "read":
        r = call("file.read", path=args[0])
        sys.stdout.write(r.get("text", "") if "text" in r else f"(binary, {r['size']} bytes)\n")
    elif sub == "write":
        content = sys.stdin.read() if len(args) < 2 or args[1] == "-" else " ".join(args[1:])
        out(call("file.write", path=args[0], content=content))
    elif sub == "edit":
        out(call("file.edit", path=args[0], old=args[1], new=args[2]))
    elif sub in ("ls", "list"):
        table(call("file.list", path=args[0] if args else "."), ["name", "kind", "size", "mode", "owner", "group"])
    elif sub == "stat":
        out(call("file.stat", path=args[0]))
    elif sub in ("rm", "delete"):
        out(call("file.delete", path=args[0], recursive="-r" in args))
    elif sub == "mkdir":
        out(call("file.mkdir", path=args[0]))
    elif sub in ("cp", "copy"):
        out(call("file.copy", src=args[0], dst=args[1]))
    elif sub in ("mv", "move"):
        out(call("file.move", src=args[0], dst=args[1]))
    elif sub == "chmod":
        out(call("file.chmod", mode=args[0], path=args[1]))
    elif sub == "history":
        table(call("file.history", path=args[0] if args else None),
              ["id", "op", "path", "note"])
    elif sub == "revert":
        out(call("file.revert", history_id=args[0]))
    else:
        raise SystemExit(f"unknown: arc file {sub}")


def cmd_root(args):
    if not args:
        raise SystemExit("usage: arc root CMD...")
    r = call("exec", cmd=args if len(args) > 1 else args[0], cwd=os.getcwd(), timeout=7200)
    sys.stdout.write(r["stdout"])
    sys.stderr.write(r["stderr"])
    return r["code"]


def cmd_screen(args):
    sub = args.pop(0) if args else "shot"
    if sub == "shot":
        grid = flag(args, "--grid", False, has_value=False)
        o = flag(args, "-o")
        r = call("screen.shot", target=args[0] if args else "screen", grid=grid)
        if o:
            import shutil
            shutil.copy(r["path"], o)
            r["path"] = o
        out(r if JSON else f"{r['path']}  ({r['width']}x{r['height']}, shot={r['shot']}, scale={r['scale']})")
    elif sub == "ocr":
        r = call("screen.ocr", target=args[0] if args else "screen")
        if JSON:
            return out(r)
        for l in r["lines"]:
            print(f"{l['center'][0]:>5},{l['center'][1]:<5} {l['text']}")
    elif sub == "find":
        out(call("screen.find_text", text=" ".join(args)))
    elif sub == "watch":
        out(call("screen.watch", target=args[0] if args else "screen"))
    elif sub == "pixel":
        out(call("screen.pixel", x=int(args[0]), y=int(args[1])))
    else:
        raise SystemExit(f"unknown: arc screen {sub}")


def cmd_input(args):
    sub = args.pop(0)
    n = lambda i: float(args[i])
    if sub == "click":
        btn = flag(args, "--button", "left")
        out(call("input.click", x=n(0) if args else None, y=n(1) if len(args) > 1 else None, button=btn,
                 count=int(flag(args, "--count", 1))))
    elif sub == "double":
        out(call("input.click", x=n(0), y=n(1), count=2))
    elif sub == "right":
        out(call("input.click", x=n(0), y=n(1), button="right"))
    elif sub == "move":
        out(call("input.move", x=n(0), y=n(1)))
    elif sub == "type":
        out(call("input.type", text=" ".join(args)))
    elif sub == "key":
        out(call("input.key", keys=args[0], repeat=int(args[1]) if len(args) > 1 else 1))
    elif sub == "scroll":
        out(call("input.scroll", dy=int(args[0]) if args else 3))
    elif sub == "drag":
        out(call("input.drag", x1=n(0), y1=n(1), x2=n(2), y2=n(3)))
    elif sub == "hold":
        out(call("input.hold", keys=args[0], ms=int(args[1]) if len(args) > 1 else 500))
    elif sub == "rel":
        out(call("input.mouse_rel", dx=int(args[0]), dy=int(args[1])))
    elif sub == "cursor":
        out(call("input.cursor"))
    else:
        raise SystemExit(f"unknown: arc input {sub}")


def cmd_win(args):
    sub = args.pop(0) if args else "list"
    if sub == "list":
        table(call("win.list"), ["workspace", "class", "title", "address", "focused"])
    elif sub == "active":
        out(call("win.active"))
    elif sub == "focus":
        out(call("win.focus", window=" ".join(args)))
    elif sub == "close":
        out(call("win.close", window=" ".join(args) or "active"))
    elif sub in ("float", "tile", "fullscreen", "maximize", "pin", "center"):
        out(call("win.action", action=sub, window=" ".join(args) or "active"))
    elif sub == "move":
        out(call("win.action", action="move", x=int(args[0]), y=int(args[1]), window=args[2] if len(args) > 2 else "active"))
    elif sub == "resize":
        out(call("win.action", action="resize", w=int(args[0]), h=int(args[1]), window=args[2] if len(args) > 2 else "active"))
    elif sub in ("to", "send"):
        out(call("win.action", action="to_workspace", workspace=args[0], window=args[1] if len(args) > 1 else "active"))
    elif sub == "ws":
        out(call("ws.switch", workspace=args[0]) if args else call("ws.list"))
    else:
        raise SystemExit(f"unknown: arc win {sub}")


def cmd_app(args):
    sub = args.pop(0) if args else "list"
    if sub == "list":
        table(call("app.list", query=args[0] if args else None), ["name", "id", "comment"])
    elif sub in ("launch", "open", "run"):
        ws = flag(args, "--ws")
        out(call("app.launch", name=" ".join(args), workspace=ws))
    elif sub == "running":
        out(call("app.running"))
    else:
        raise SystemExit(f"unknown: arc app {sub}")


def cmd_game(args):
    sub = args.pop(0) if args else "list"
    if sub == "list":
        table(call("game.list"), ["id", "name", "source"])
    elif sub in ("launch", "play", "run"):
        out(call("game.launch", game=" ".join(args)))
    elif sub == "stop":
        out(call("game.stop", game=" ".join(args)))
    elif sub == "mode":
        out(call("game.mode", action=args[0] if args else "toggle"))
    else:
        raise SystemExit(f"unknown: arc game {sub}")


def cmd_totality(args):
    action = args[0] if args else "toggle"
    if action not in ("on", "off", "toggle", "status"):
        raise SystemExit("usage: arc totality [on|off|toggle|status]")
    try:
        out(call("totality.mode", action=action))
    except SystemExit:
        raise
    except Exception:  # no session service: do it here (off must always be able to wake everything)
        from .session import totality
        out(totality.mode(action))


def cmd_ui(args):
    sub = args.pop(0) if args else "tree"
    win = flag(args, "--window", "active")
    if sub == "tree":
        r = call("ui.tree", window=win)
        if JSON:
            return out(r)
        for n in r["nodes"]:
            print(f"{n['path']:<16} {n['role']:<16} {n['name'][:50]!r:<52} {n.get('center', '')}")
    elif sub == "find":
        out(call("ui.find", name=" ".join(args), window=win))
    elif sub == "press":
        out(call("ui.press", name=" ".join(args), window=win))
    elif sub == "set-text":
        out(call("ui.set_text", name=args[0], text=" ".join(args[1:]), window=win))
    else:
        raise SystemExit(f"unknown: arc ui {sub}")


def cmd_snap(args):
    sub = args.pop(0) if args else "list"
    if sub == "list":
        r = call("snap.list")
        if not r["supported"]:
            print("snapshots need a btrfs root (whole-disk install)")
        table(r["snapshots"], ["id", "label"])
    elif sub == "create":
        out(call("snap.create", label=" ".join(args) or "manual"))
    elif sub == "rollback":
        out(call("snap.rollback", id=args[0]))
    elif sub == "delete":
        out(call("snap.delete", id=args[0]))
    else:
        raise SystemExit(f"unknown: arc snap {sub}")


def cmd_sys(args):
    sub = args.pop(0) if args else "info"
    if sub == "info":
        out(call("sys.info"))
    elif sub == "hostname":
        out(call("sys.hostname", name=args[0] if args else None))
    elif sub == "timezone":
        out(call("sys.timezone", tz=args[0] if args else None))
    elif sub == "locale":
        out(call("sys.locale", lang=args[0] if args else None))
    elif sub == "cmdline":
        add = flag(args, "--add")
        rm = flag(args, "--remove")
        out(call("sys.cmdline", add=add, remove=rm))
    elif sub == "users":
        table(call("sys.users"), ["name", "uid", "shell", "groups"])
    elif sub in ("reboot", "poweroff", "suspend", "hibernate"):
        out(call("sys.power", action=sub))
    else:
        raise SystemExit(f"unknown: arc sys {sub}")


def cmd_history(args):
    n = int(flag(args, "-n", 30))
    agent = flag(args, "--agent")
    rows = call("actions.tail", n=n, agent=agent)
    if JSON:
        return out(rows)
    for r in rows:
        print(f"{time.strftime('%m-%d %H:%M:%S', time.localtime(r['time']))} {r['agent']:<8} {'ok ' if r['ok'] else 'ERR'} "
              f"{r['method']:<16} {json.dumps(r['params'])[:90]}")


def cmd_events(args):
    for r in call("events.tail", n=int(args[0]) if args else 30):
        print(f"{time.strftime('%m-%d %H:%M:%S', time.localtime(r['time']))} {r['kind']:<14} {r.get('unit') or '':<28} {r['message']}")


def cmd_stop(args):
    out(call("stop"))


def cmd_routine(args):
    os.execvp("arclight-routine", ["arclight-routine"] + args)


def cmd_ask(args):
    os.execvp("arclight-ask", ["arclight-ask"] + args)


def cmd_doctor(args):
    """One-shot health check: what is wrong, and the command that fixes it."""
    import shutil as _sh
    from pathlib import Path as _P
    G, R, Y, N = "\033[38;2;63;214;154m", "\033[38;2;212;43;43m", "\033[38;2;224;176;64m", "\033[0m"
    W, D = "\033[1;38;2;242;245;255m", "\033[38;2;138;151;174m"
    rows = []

    def chk(ok, what, fix=""):
        rows.append({"ok": ok, "check": what, "fix": "" if ok else fix})

    try:
        i = call("sys.info")
        chk(not i["failed_units"], "no failed system services" + (f" ({', '.join(i['failed_units'])})" if i["failed_units"] else ""),
            "arc log errors   then   arc svc restart UNIT")
        for d in i["disks"]:
            if d["mount"] in ("/", "/home"):
                free = d["free"] / max(1, d["size"])
                chk(free > 0.08, f"{d['mount']} has {human(d['free'])} free", "arc pkg orphans; clear ~/.cache; arc snap prune")
        chk(True, "arclightd (root API) answers")
    except C.Unavailable:
        chk(False, "arclightd (root API) answers", "arc root systemctl enable --now arclightd")
    try:
        call("win.active")
        chk(True, "arclight-session (desktop API) answers")
    except C.Unavailable:
        chk(False, "arclight-session (desktop API) answers", "systemctl --user restart arclight-session")
    except C.RemoteError:
        chk(True, "arclight-session (desktop API) answers")
    try:
        user_failed = [u["unit"] for u in C.call("svc.list", _user=True, state="failed")]
        chk(not user_failed, "no failed user services" + (f" ({', '.join(user_failed)})" if user_failed else ""),
            "systemctl --user status UNIT")
    except Exception:
        pass
    chk(os.access("/dev/uinput", os.W_OK), "the AI's virtual keyboard/mouse can be created (/dev/uinput)",
        "log out and in again (group arclight), or: arc root modprobe uinput")
    home = _P.home()
    cj = home / ".claude.json"
    chk(cj.exists() and '"arclight"' in cj.read_text(errors="ignore"), "Claude Code has the arclight tools (MCP)",
        "arclight-firstrun --force")
    cc = home / ".codex/config.toml"
    chk(cc.exists() and "[mcp_servers.arclight]" in cc.read_text(errors="ignore"), "Codex has the arclight tools (MCP)",
        "arclight-firstrun --force")
    chk(bool(_sh.which("claude") or (home / ".local/bin/claude").exists()), "Claude Code is installed",
        "curl -fsSL https://claude.ai/install.sh | bash")
    if _sh.which("hyprctl") and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        import subprocess as _sp
        errs = _sp.run(["hyprctl", "configerrors"], capture_output=True, text=True).stdout.strip()
        chk(not errs, "Hyprland config has no errors" + (f": {errs[:120]}" if errs else ""), "hyprctl configerrors")
    pend = _P("/var/lib/arclight/pending-packages.txt")
    if pend.exists() and pend.read_text().strip():
        chk(False, f"{len(pend.read_text().split())} packages still waiting to install", "arc root arclight-pkgsync")
    # Eclipse layer: boot splash, home ownership, routines
    pc = _P("/etc/plymouth/plymouthd.conf")
    if pc.exists():
        chk("Theme=eclipse" in pc.read_text(errors="ignore") and _P("/usr/share/plymouth/themes/eclipse").is_dir(),
            "the eclipse boot animation is set up", "arc root plymouth-set-default-theme -R eclipse")
    bad_owned = [str(p) for p in (home, home / ".config", home / ".local", home / ".local/share", home / ".local/state")
                 if p.exists() and p.stat().st_uid != os.getuid()]
    chk(not bad_owned, "your home folders belong to you" + (f" (not: {', '.join(bad_owned)})" if bad_owned else ""),
        f"arc root chown {os.getuid()}:{os.getgid()} " + " ".join(bad_owned) if bad_owned else "")
    try:
        from . import routines as _rt
        for r in _rt.listing():
            logs = sorted((_rt.LOGS / r["id"]).glob("*.log"))
            if logs:
                head = logs[-1].read_text(errors="ignore").splitlines()[:1]
                ok = bool(head) and "exit 0)" in head[0]
                chk(ok, f"routine \u201c{r['name']}\u201d: last run " + ("worked" if ok else "failed"),
                    "" if ok else f"arc routine log {r['id']}")
    except Exception:
        pass
    if JSON:
        return out(rows)
    from . import identity
    print(f"\n  {W}{identity.os_name()}{N}  {D}health check{N}\n")
    for r in rows:
        print(f"  {G + '✓' if r['ok'] else R + '✗'}{N} {r['check']}" + (f"\n      {Y}fix:{N} {r['fix']}" if r["fix"] else ""))
    bad = sum(not r["ok"] for r in rows)
    print(f"\n  {G + 'All good.' if not bad else Y + str(bad) + ' thing(s) to fix.'}{N}")
    return 1 if bad else 0


def cmd_update(args):
    os.execvp("arclight-update", ["arclight-update"] + args)


def cmd_call(args):
    method = args.pop(0)
    user = flag(args, "--user", False, has_value=False)
    out(C.call(method, _user=user, **kv(args)))


def cmd_api(args):
    which = args[0] if args else None
    for w in ([which] if which else ["system", "session"]):
        try:
            d = C.client(w).call("api.describe")
        except C.Unavailable as e:
            print(f"[{w}] {e}")
            continue
        if JSON:
            out(d)
            continue
        print(f"== {w}")
        for m, info in d.items():
            ps = ", ".join(f"{k}={json.dumps(v)}" if v is not None else k for k, v in info["params"].items() if k != "_peer")
            print(f"  {m}({ps})")
            if info["doc"]:
                print(f"      {info['doc'].splitlines()[0]}")


COMMANDS = {"get": cmd_get, "set": cmd_set, "settings": cmd_settings, "pkg": cmd_pkg, "svc": cmd_svc, "log": cmd_log,
            "logs": cmd_log, "file": cmd_file, "root": cmd_root, "screen": cmd_screen, "input": cmd_input,
            "win": cmd_win, "app": cmd_app, "game": cmd_game, "totality": cmd_totality, "ui": cmd_ui, "snap": cmd_snap, "sys": cmd_sys,
            "history": cmd_history, "events": cmd_events, "stop": cmd_stop, "ask": cmd_ask, "routine": cmd_routine, "call": cmd_call,
            "api": cmd_api, "info": cmd_overview, "update": cmd_update, "doctor": cmd_doctor}


def main(argv=None):
    global JSON
    args = list(sys.argv[1:] if argv is None else argv)
    if "--json" in args:
        args.remove("--json")
        JSON = True
    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    try:
        if not args:
            return cmd_overview([]) or 0
        fn = COMMANDS.get(args[0])
        if not fn:
            print(f"arc: unknown command {args[0]!r}\n{__doc__}", file=sys.stderr)
            return 2
        return fn(args[1:]) or 0
    except C.RemoteError as e:
        print(f"arc: {e.message}", file=sys.stderr)
        return 1
    except C.Unavailable as e:
        print(f"arc: {e}", file=sys.stderr)
        return 3
    except (IndexError, ValueError) as e:
        print(f"arc: missing or bad argument ({e}); see arc --help", file=sys.stderr)
        return 2
