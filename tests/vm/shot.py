"""Screenshot a QEMU VM through its monitor socket: shot.py MONITOR_SOCK OUT.png"""
import os
import socket
import subprocess
import sys
import tempfile
import time

s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
time.sleep(0.3)
s.recv(4096)
ppm = tempfile.mktemp(suffix=".ppm")
s.sendall(f"screendump {ppm}\n".encode())
for _ in range(50):
    time.sleep(0.2)
    if os.path.exists(ppm) and os.path.getsize(ppm) > 1000:
        break
time.sleep(0.5)
s.close()
subprocess.run(["magick", ppm, "-resize", "50%", sys.argv[2]], check=True)
os.unlink(ppm)
print(sys.argv[2])
