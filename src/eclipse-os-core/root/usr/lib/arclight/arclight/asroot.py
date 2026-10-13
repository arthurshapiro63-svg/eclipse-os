"""arclight-asroot CMD...: run one command as root through arclightd (a sudo replacement with no
password, for members of the arclight group). yay uses it as its --sudo."""
import os
import sys

from . import client as C


def main():
    args = sys.argv[1:]
    while args and args[0] in ("-E", "-n", "--preserve-env", "-H", "-S"):
        args.pop(0)  # sudo-style flags callers pass out of habit
    if not args:
        print("usage: arclight-asroot CMD...", file=sys.stderr)
        return 2
    if args[0] == "-v":
        return 0  # 'sudo -v' credential refresh: nothing to refresh
    try:
        r = C.call("exec", cmd=args, cwd=os.getcwd(), timeout=7200)
    except C.Unavailable as e:
        print(f"arclight-asroot: {e}", file=sys.stderr)
        return 1
    except C.RemoteError as e:
        print(f"arclight-asroot: {e.message}", file=sys.stderr)
        return 1
    except (ConnectionError, OSError) as e:
        print(f"arclight-asroot: lost the connection to arclightd ({e}); the command may still have finished",
              file=sys.stderr)
        return 1
    sys.stdout.write(r["stdout"])
    sys.stderr.write(r["stderr"])
    return r["code"] if r["code"] >= 0 else 1
