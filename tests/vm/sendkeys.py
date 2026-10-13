"""Type text into a QEMU VM through its monitor (for boot-time prompts): sendkeys.py MONITOR_SOCK TEXT [--enter]"""
import socket
import sys
import time

NAMES = {"-": "minus", " ": "spc", ".": "dot", "/": "slash", "_": "shift-minus", ":": "shift-semicolon"}
s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
time.sleep(0.3)
s.recv(4096)
for ch in sys.argv[2]:
    k = NAMES.get(ch) or (f"shift-{ch.lower()}" if ch.isupper() else ch)
    s.sendall(f"sendkey {k}\n".encode())
    time.sleep(0.08)
if "--enter" in sys.argv[3:]:
    s.sendall(b"sendkey ret\n")
time.sleep(0.3)
s.close()
