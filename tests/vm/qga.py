"""Tiny QEMU guest-agent client for the VM tests.

  qga.py SOCK ping | exec 'shell cmd' [timeout] | push LOCAL REMOTE | pull REMOTE LOCAL | wait [timeout]
"""
import base64, json, socket, sys, time
def call(sock, cmd, args=None, timeout=30):
    s = socket.socket(socket.AF_UNIX); s.settimeout(timeout); s.connect(sock)
    sid = int(time.time()) % 100000
    s.sendall(json.dumps({"execute": "guest-sync", "arguments": {"id": sid}}).encode())
    f = s.makefile()
    while json.loads(f.readline()).get("return") != sid: pass
    s.sendall(json.dumps({"execute": cmd, **({"arguments": args} if args else {})}).encode())
    r = json.loads(f.readline()); s.close()
    if "error" in r: raise SystemExit(r["error"])
    return r["return"]
sock, op = sys.argv[1], sys.argv[2]
if op == "ping": call(sock, "guest-ping", timeout=5); print("pong")
elif op == "push":
    h = call(sock, "guest-file-open", {"path": sys.argv[4], "mode": "w"})
    call(sock, "guest-file-write", {"handle": h, "buf-b64": base64.b64encode(open(sys.argv[3], "rb").read()).decode()})
    call(sock, "guest-file-close", {"handle": h}); print("pushed")
elif op == "pull":
    h = call(sock, "guest-file-open", {"path": sys.argv[3], "mode": "r"})
    data = b""
    while True:
        r = call(sock, "guest-file-read", {"handle": h, "count": 1 << 20})
        data += base64.b64decode(r["buf-b64"])
        if r.get("eof"):
            break
    call(sock, "guest-file-close", {"handle": h})
    open(sys.argv[4], "wb").write(data); print(f"pulled {len(data)} bytes")
elif op == "wait":
    limit = time.time() + (float(sys.argv[3]) if len(sys.argv) > 3 else 300)
    while time.time() < limit:
        try:
            call(sock, "guest-ping", timeout=3); print("up"); break
        except (OSError, SystemExit, ValueError):
            time.sleep(2)
    else:
        raise SystemExit("guest agent did not answer")
elif op == "exec":
    limit = float(sys.argv[4]) if len(sys.argv) > 4 else 120
    pid = call(sock, "guest-exec", {"path": "/bin/bash", "arg": ["-c", sys.argv[3]], "capture-output": True})["pid"]
    t0 = time.time()
    while True:
        st = call(sock, "guest-exec-status", {"pid": pid})
        if st["exited"]: break
        if time.time() - t0 > limit: raise SystemExit("timeout")
        time.sleep(2)
    for k in ("out-data", "err-data"):
        if st.get(k): sys.stdout.write(base64.b64decode(st[k]).decode(errors="replace"))
    print(f"[exit {st.get('exitcode')}]")
    sys.exit(st.get("exitcode") or 0)
