"""Virtual input devices on /dev/uinput (keyboard + mouse), no dependencies.

The devices are created once and kept open for the life of the session daemon:
libinput needs a moment to pick up a new device, and the first events sent to a
brand-new device are often lost. They look like real hardware to every app,
XWayland and Proton games included.

Absolute pointer positioning is done by the compositor (exact, no acceleration);
this module sends buttons, wheel, relative motion (for game cameras) and keys.
"""
import fcntl
import os
import struct
import threading
import time

EV_SYN, EV_KEY, EV_REL, EV_MSC = 0x00, 0x01, 0x02, 0x04
SYN_REPORT = 0
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0x00, 0x01, 0x06, 0x08
REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES = 0x0B, 0x0C
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA = 0x110, 0x111, 0x112, 0x113, 0x114
BUS_VIRTUAL = 0x06

UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = 0x405C5503
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566

EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit: timeval + type + code + value

# Linux key codes (input-event-codes.h)
KEYS = {
    "esc": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11, "minus": 12,
    "equal": 13, "backspace": 14, "tab": 15, "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22,
    "i": 23, "o": 24, "p": 25, "leftbrace": 26, "rightbrace": 27, "enter": 28, "leftctrl": 29, "a": 30, "s": 31,
    "d": 32, "f": 33, "g": 34, "h": 35, "j": 36, "k": 37, "l": 38, "semicolon": 39, "apostrophe": 40, "grave": 41,
    "leftshift": 42, "backslash": 43, "z": 44, "x": 45, "c": 46, "v": 47, "b": 48, "n": 49, "m": 50, "comma": 51,
    "dot": 52, "slash": 53, "rightshift": 54, "kpasterisk": 55, "leftalt": 56, "space": 57, "capslock": 58,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64, "f7": 65, "f8": 66, "f9": 67, "f10": 68,
    "numlock": 69, "scrolllock": 70, "kp7": 71, "kp8": 72, "kp9": 73, "kpminus": 74, "kp4": 75, "kp5": 76,
    "kp6": 77, "kpplus": 78, "kp1": 79, "kp2": 80, "kp3": 81, "kp0": 82, "kpdot": 83, "f11": 87, "f12": 88,
    "kpenter": 96, "rightctrl": 97, "kpslash": 98, "sysrq": 99, "rightalt": 100, "home": 102, "up": 103,
    "pageup": 104, "left": 105, "right": 106, "end": 107, "down": 108, "pagedown": 109, "insert": 110,
    "delete": 111, "mute": 113, "volumedown": 114, "volumeup": 115, "power": 116, "pause": 119,
    "leftmeta": 125, "rightmeta": 126, "compose": 127, "f13": 183, "f14": 184, "f15": 185,
    "playpause": 164, "nextsong": 163, "previoussong": 165, "print": 99,
}
ALIASES = {
    "ctrl": "leftctrl", "control": "leftctrl", "lctrl": "leftctrl", "rctrl": "rightctrl", "shift": "leftshift",
    "lshift": "leftshift", "rshift": "rightshift", "alt": "leftalt", "lalt": "leftalt", "ralt": "rightalt",
    "altgr": "rightalt", "super": "leftmeta", "meta": "leftmeta", "win": "leftmeta", "cmd": "leftmeta",
    "mod": "leftmeta", "return": "enter", "ret": "enter", "escape": "esc", "del": "delete", "bksp": "backspace",
    "pgup": "pageup", "pgdn": "pagedown", "pgdown": "pagedown", "ins": "insert", "spacebar": "space",
    "-": "minus", "=": "equal", "[": "leftbrace", "]": "rightbrace", ";": "semicolon", "'": "apostrophe",
    "`": "grave", "\\": "backslash", ",": "comma", ".": "dot", "/": "slash", " ": "space", "period": "dot",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right", "printscreen": "print",
    "prtsc": "print", "caps": "capslock", "menu": "compose",
}
# characters -> (key, shift) on a US layout
CHARS = {}
for c in "abcdefghijklmnopqrstuvwxyz":
    CHARS[c] = (c, False)
    CHARS[c.upper()] = (c, True)
for c in "1234567890":
    CHARS[c] = (c, False)
for c, k in zip("!@#$%^&*()", "1234567890"):
    CHARS[c] = (k, True)
for c, (k, s) in {" ": ("space", False), "\n": ("enter", False), "\t": ("tab", False), "-": ("minus", False),
                  "_": ("minus", True), "=": ("equal", False), "+": ("equal", True), "[": ("leftbrace", False),
                  "{": ("leftbrace", True), "]": ("rightbrace", False), "}": ("rightbrace", True),
                  ";": ("semicolon", False), ":": ("semicolon", True), "'": ("apostrophe", False),
                  '"': ("apostrophe", True), "`": ("grave", False), "~": ("grave", True), "\\": ("backslash", False),
                  "|": ("backslash", True), ",": ("comma", False), "<": ("comma", True), ".": ("dot", False),
                  ">": ("dot", True), "/": ("slash", False), "?": ("slash", True)}.items():
    CHARS[c] = (k, s)

BUTTONS = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE, "back": BTN_SIDE, "forward": BTN_EXTRA,
           "side": BTN_SIDE, "extra": BTN_EXTRA}


def keycode(name):
    n = str(name).strip().lower()
    n = ALIASES.get(n, n)
    if n in KEYS:
        return KEYS[n]
    if n.startswith("key_") and n[4:] in KEYS:
        return KEYS[n[4:]]
    if n.isdigit() and int(n) > 11:
        return int(n)  # raw code
    raise ValueError(f"unknown key {name!r}")


def parse_chord(chord):
    """'ctrl+shift+t' -> [29, 42, 20]. Also accepts lists."""
    parts = chord if isinstance(chord, (list, tuple)) else [p for p in str(chord).replace(" ", "").split("+") if p] or ["+"]
    if isinstance(chord, str) and chord.endswith("++"):
        parts = parts + ["equal"]  # 'ctrl++' = ctrl + plus key
    return [keycode(p) for p in parts]


class Device:
    def __init__(self, name, keys=(), rels=(), product=0x1):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        self.lock = threading.Lock()
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_SYN)
        if keys:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for k in keys:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, k)
        if rels:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
            for r in rels:
                fcntl.ioctl(self.fd, UI_SET_RELBIT, r)
        # struct uinput_setup { struct input_id {u16 bustype, vendor, product, version}; char name[80]; u32 ff_effects_max; }
        setup = struct.pack("HHHH80sI", BUS_VIRTUAL, 0xA4C1, product, 1, name.encode()[:79], 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        self.created = time.monotonic()

    def emit(self, etype, code, value, syn=True):
        with self.lock:
            now = time.time()
            sec, usec = int(now), int((now % 1) * 1e6)
            data = EVENT.pack(sec, usec, etype, code, value)
            if syn:
                data += EVENT.pack(sec, usec, EV_SYN, SYN_REPORT, 0)
            os.write(self.fd, data)

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


class VirtualInput:
    """Keyboard + mouse pair. Tracks held keys/buttons so `release_all` can always unstick them."""

    def __init__(self):
        self.kbd = Device("Arclight Virtual Keyboard", keys=sorted(set(KEYS.values())), product=0x1)
        self.mouse = Device("Arclight Virtual Mouse", keys=sorted(BUTTONS.values()),
                            rels=(REL_X, REL_Y, REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES), product=0x2)
        self.held_keys = set()
        self.held_buttons = set()
        time.sleep(0.4)  # let libinput/Hyprland register both devices

    # keys
    def key(self, code, down):
        self.kbd.emit(EV_KEY, code, 1 if down else 0)
        (self.held_keys.add if down else self.held_keys.discard)(code)

    def tap(self, codes, hold_ms=30, gap_ms=8):
        for c in codes:
            self.key(c, True)
            time.sleep(gap_ms / 1000)
        time.sleep(hold_ms / 1000)
        for c in reversed(codes):
            self.key(c, False)
            time.sleep(gap_ms / 1000)

    def type_ascii(self, text, delay_ms=12):
        """Type text the US-layout keymap can express. Returns characters it could not type."""
        missing = []
        shift = KEYS["leftshift"]
        for ch in text:
            if ch == "\r":
                continue
            m = CHARS.get(ch)
            if not m:
                missing.append(ch)
                continue
            k, s = m
            codes = ([shift] if s else []) + [KEYS[k]]
            self.tap(codes, hold_ms=max(4, delay_ms // 2), gap_ms=2)
            time.sleep(delay_ms / 1000)
        return missing

    # mouse
    def button(self, name, down):
        code = BUTTONS[name] if isinstance(name, str) else name
        self.mouse.emit(EV_KEY, code, 1 if down else 0)
        (self.held_buttons.add if down else self.held_buttons.discard)(code)

    def click(self, name="left", count=1, interval_ms=60):
        for i in range(count):
            self.button(name, True)
            time.sleep(0.035)
            self.button(name, False)
            if i + 1 < count:
                time.sleep(interval_ms / 1000)

    def rel(self, dx, dy):
        with self.mouse.lock:
            now = time.time()
            sec, usec = int(now), int((now % 1) * 1e6)
            data = b""
            if dx:
                data += EVENT.pack(sec, usec, EV_REL, REL_X, int(dx))
            if dy:
                data += EVENT.pack(sec, usec, EV_REL, REL_Y, int(dy))
            if data:
                data += EVENT.pack(sec, usec, EV_SYN, SYN_REPORT, 0)
                os.write(self.mouse.fd, data)

    def rel_smooth(self, dx, dy, duration_ms=0, steps=None):
        steps = steps or max(1, int(duration_ms / 8)) if duration_ms else 1
        sx = sy = 0
        for i in range(1, steps + 1):
            tx, ty = round(dx * i / steps), round(dy * i / steps)
            self.rel(tx - sx, ty - sy)
            sx, sy = tx, ty
            if duration_ms:
                time.sleep(duration_ms / 1000 / steps)

    def wheel(self, dy=0, dx=0):
        """dy > 0 scrolls down (content moves up), in notches."""
        for _ in range(abs(int(dy))):
            self.mouse.emit(EV_REL, REL_WHEEL, -1 if dy > 0 else 1, syn=False)
            self.mouse.emit(EV_REL, REL_WHEEL_HI_RES, -120 if dy > 0 else 120)
            time.sleep(0.03)
        for _ in range(abs(int(dx))):
            self.mouse.emit(EV_REL, REL_HWHEEL, 1 if dx > 0 else -1, syn=False)
            self.mouse.emit(EV_REL, REL_HWHEEL_HI_RES, 120 if dx > 0 else -120)
            time.sleep(0.03)

    def release_all(self):
        for c in list(self.held_keys):
            self.key(c, False)
        for b in list(self.held_buttons):
            self.button(b, False)
        return True

    def close(self):
        self.release_all()
        self.kbd.close()
        self.mouse.close()
