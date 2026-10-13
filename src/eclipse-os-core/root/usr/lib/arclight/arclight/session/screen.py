"""Eyes: screenshots of the layout / a monitor / a region / any single window, OCR, frame bursts.

Every shot records its transform (origin + scale) under a shot id, so the caller can
give click coordinates in the pixels of the image it looked at:
    global_x = origin_x + image_x / scale
"""
import collections
import io
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from ..rpc import RPCError
from ..util import runtime_dir
from . import hypr

try:
    from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageStat
except ImportError:  # the session daemon reports this instead of crashing
    Image = None

SHOTS = collections.OrderedDict()
_lock = threading.Lock()
MAX_SHOTS = 64


def shot_dir():
    d = runtime_dir() / "shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _need_pil():
    if Image is None:
        raise RPCError("python-pillow is not installed")


def _grim(args, timeout=15):
    p = subprocess.run(["grim"] + args + ["-t", "ppm", "-"], capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RPCError(f"grim {' '.join(args)} failed: {p.stderr.decode(errors='replace').strip()}")
    return Image.open(io.BytesIO(p.stdout)).convert("RGB")


def _font(size):
    for f in ("/usr/share/fonts/TTF/JetBrainsMono-Bold.ttf", "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf",
              "/usr/share/fonts/noto/NotoSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"):
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                pass
    return ImageFont.load_default()


def capture(target="screen", cursor=False):
    """Return (PIL image, origin (x, y), logical size (w, h), info dict) for a target.
    target: screen | active | monitor:NAME | window:SELECTOR | region:X,Y,W,H"""
    _need_pil()
    t = str(target or "screen")
    info = {"target": t}
    extra = ["-c"] if cursor else []
    if t in ("screen", "all", "layout"):
        x0, y0, x1, y1 = hypr.layout_box()
        img = _grim(extra)
        return img, (x0, y0), (x1 - x0, y1 - y0), info
    if t.startswith("monitor:") or t == "monitor":
        name = t.split(":", 1)[1] if ":" in t else None
        mons = hypr.monitors()
        m = next((m for m in mons if m["name"] == name), None) if name else next((m for m in mons if m.get("focused")), mons[0])
        if not m:
            raise RPCError(f"no monitor {name}; have {[m['name'] for m in mons]}")
        img = _grim(extra + ["-o", m["name"]])
        sc = m.get("scale", 1)
        info["monitor"] = m["name"]
        return img, (m["x"], m["y"]), (round(m["width"] / sc), round(m["height"] / sc)), info
    if t.startswith("region:"):
        try:
            x, y, w, h = [int(float(v)) for v in re.split(r"[ ,x]+", t.split(":", 1)[1].strip())]
        except ValueError:
            raise RPCError("region must be region:X,Y,W,H")
        img = _grim(extra + ["-g", f"{x},{y} {w}x{h}"])
        return img, (x, y), (w, h), info
    if t == "active" or t.startswith("window:") or t.startswith("window"):
        selector = "active" if t == "active" else t.split(":", 1)[1] if ":" in t else "active"
        c = hypr.find_window(selector)
        info["window"] = hypr.summarize(c)
        sid = c.get("stableId")
        img = None
        if sid:
            try:
                img = _grim(extra + ["-T", str(sid)])
            except RPCError:
                img = None
        if img is None:  # fall back to cropping the screen (only works for visible windows)
            x, y = c["at"]
            w, h = c["size"]
            img = _grim(extra + ["-g", f"{x},{y} {w}x{h}"])
            info["method"] = "crop"
        else:
            info["method"] = "toplevel"
        info["clickable"] = bool(c.get("visible", True)) and c["workspace"]["id"] in _visible_ws_ids()
        return img, tuple(c["at"]), tuple(c["size"]), info
    raise RPCError("target must be screen | active | monitor:NAME | window:SELECTOR | region:X,Y,W,H")


def _visible_ws_ids():
    ids = set()
    for m in hypr.monitors():
        ids.add(m["activeWorkspace"]["id"])
        if m.get("specialWorkspace", {}).get("id"):
            ids.add(m["specialWorkspace"]["id"])
    return ids


def _grid(img, origin, logical, step=100):
    """Overlay a labelled coordinate grid in GLOBAL logical pixels."""
    d = ImageDraw.Draw(img, "RGBA")
    sx = img.width / max(1, logical[0])
    sy = img.height / max(1, logical[1])
    font = _font(max(10, int(11 * sx)))
    gx0 = (origin[0] // step + 1) * step
    for gx in range(int(gx0), int(origin[0] + logical[0]), step):
        px = (gx - origin[0]) * sx
        major = gx % 500 == 0
        d.line([(px, 0), (px, img.height)], fill=(255, 64, 160, 110 if major else 55), width=1)
        d.text((px + 2, 2), str(gx), fill=(255, 120, 190, 230), font=font)
    gy0 = (origin[1] // step + 1) * step
    for gy in range(int(gy0), int(origin[1] + logical[1]), step):
        py = (gy - origin[1]) * sy
        major = gy % 500 == 0
        d.line([(0, py), (img.width, py)], fill=(255, 64, 160, 110 if major else 55), width=1)
        d.text((2, py + 2), str(gy), fill=(255, 120, 190, 230), font=font)
    return img


def shot(target="screen", max_width=1568, grid=False, cursor=False, fmt="png", quality=85, mark=None):
    """Take a screenshot. Returns a file path plus the transform needed to click on what you see.
    mark: [x, y] in global coords to draw a crosshair (to check where a click would land)."""
    img, origin, logical, info = capture(target, cursor=cursor)
    native = img.size
    # images come back in physical pixels; first map to logical so scale is relative to global coords
    scale = 1.0
    if max_width and img.width > max_width:
        scale_img = max_width / img.width
        img = img.resize((max_width, round(img.height * scale_img)), Image.LANCZOS)
    scale = img.width / max(1, logical[0])
    if grid:
        img = _grid(img, origin, logical)
    if mark:
        mx, my = (mark[0] - origin[0]) * scale, (mark[1] - origin[1]) * scale
        d = ImageDraw.Draw(img, "RGBA")
        d.ellipse([mx - 9, my - 9, mx + 9, my + 9], outline=(255, 40, 120, 255), width=2)
        d.line([(mx - 14, my), (mx + 14, my)], fill=(255, 40, 120, 255), width=1)
        d.line([(mx, my - 14), (mx, my + 14)], fill=(255, 40, 120, 255), width=1)
    sid = uuid.uuid4().hex[:8]
    ext = "jpg" if fmt in ("jpg", "jpeg") else "png"
    path = shot_dir() / f"{time.strftime('%H%M%S')}-{sid}.{ext}"
    if ext == "jpg":
        img.save(path, quality=int(quality))
    else:
        img.save(path, optimize=False, compress_level=3)
    rec = {"shot": sid, "path": str(path), "width": img.width, "height": img.height, "origin": list(origin),
           "logical_size": list(logical), "native_size": list(native), "scale": round(scale, 6), **info}
    with _lock:
        SHOTS[sid] = rec
        while len(SHOTS) > MAX_SHOTS:
            old = SHOTS.popitem(last=False)[1]
            Path(old["path"]).unlink(missing_ok=True)
    return rec


def to_global(x, y, shot_id=None):
    """Map image coords of `shot_id` (if given) to global logical coords."""
    if not shot_id:
        return float(x), float(y)
    rec = SHOTS.get(shot_id)
    if not rec:
        raise RPCError(f"unknown shot id {shot_id} (shots are kept for this session only)")
    return rec["origin"][0] + float(x) / rec["scale"], rec["origin"][1] + float(y) / rec["scale"]


def pixel(x, y):
    """Colour of one global pixel."""
    _need_pil()
    img = _grim(["-g", f"{int(x)},{int(y)} 1x1"])
    r, g, b = img.getpixel((0, 0))
    return {"x": x, "y": y, "rgb": [r, g, b], "hex": f"#{r:02X}{g:02X}{b:02X}"}


# ---------------------------------------------------------------- OCR

def ocr(target="screen", min_conf=40, lang="eng", upscale=2.0):
    """Read text on screen. Returns lines with their bounding boxes in global coordinates."""
    img, origin, logical, info = capture(target)
    sx = img.width / max(1, logical[0])
    if upscale and upscale != 1:
        img = img.resize((int(img.width * upscale), int(img.height * upscale)), Image.LANCZOS)
    k = (sx * (upscale or 1))
    with tempfile.NamedTemporaryFile(suffix=".png", dir=shot_dir(), delete=False) as f:
        img.save(f.name)
        p = subprocess.run(["tesseract", f.name, "stdout", "-l", lang, "--psm", "11", "tsv"], capture_output=True,
                           text=True, timeout=90)
        os.unlink(f.name)
    if p.returncode != 0:
        raise RPCError(f"tesseract failed: {p.stderr.strip()[:300]}")
    words = []
    for row in p.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        conf = float(c[10])
        if conf < min_conf:
            continue
        x, y, w, h = (int(v) for v in c[6:10])
        words.append({"text": c[11], "conf": round(conf), "block": int(c[2]), "par": int(c[3]), "line": int(c[4]),
                      "x": origin[0] + x / k, "y": origin[1] + y / k, "w": w / k, "h": h / k})
    lines = {}
    for wd in words:
        lines.setdefault((wd["block"], wd["par"], wd["line"]), []).append(wd)
    out = []
    for ws in lines.values():
        x0 = min(w["x"] for w in ws); y0 = min(w["y"] for w in ws)
        x1 = max(w["x"] + w["w"] for w in ws); y1 = max(w["y"] + w["h"] for w in ws)
        out.append({"text": " ".join(w["text"] for w in ws), "box": [round(x0), round(y0), round(x1 - x0), round(y1 - y0)],
                    "center": [round((x0 + x1) / 2), round((y0 + y1) / 2)], "words": ws})
    out.sort(key=lambda l: (l["box"][1], l["box"][0]))
    return {"target": target, "lines": out, **{k2: v for k2, v in info.items() if k2 != "target"}}


def find_text(text, target="screen", exact=False, min_conf=30):
    """Find text on screen; returns matches (best first) with click-ready centers in global coords.
    Tolerant by default: small words OCR drops ("AI", "OK") or one misread word still match when most of
    the phrase is there, in order. exact=true wants every word."""
    import difflib
    res = ocr(target, min_conf=min_conf)
    q = text.lower().strip()
    qt = q.split()
    hits = []
    for ln in res["lines"]:
        ws = ln["words"]
        toks = [w["text"].lower().strip(".,:;!?()[]") for w in ws]
        best = None
        for i in range(len(toks)):
            for j in range(i + 1, min(len(toks), i + len(qt) + 1) + 1):
                seg = toks[i:j]
                # words of the query found in order in this window (fuzzy per word)
                k, found = 0, 0
                for t in seg:
                    if k < len(qt) and (t == qt[k] or difflib.SequenceMatcher(None, t, qt[k]).ratio() >= 0.8):
                        found += 1
                        k += 1
                score = found / len(qt)
                if len(qt) == 1 and qt[0] in " ".join(seg) and len(seg) == 1:
                    score = 1.0
                need = 1.0 if exact else (1.0 if len(qt) == 1 else 0.6)
                if score >= need and (best is None or score > best[0] or (score == best[0] and j - i < best[2] - best[1])):
                    best = (score, i, j)
        if best:
            score, i, j = best
            part = ws[i:j]
            x0 = min(w["x"] for w in part); y0 = min(w["y"] for w in part)
            x1 = max(w["x"] + w["w"] for w in part); y1 = max(w["y"] + w["h"] for w in part)
            hits.append({"text": " ".join(w["text"] for w in part), "line": ln["text"], "score": round(score, 2),
                         "center": [round((x0 + x1) / 2), round((y0 + y1) / 2)],
                         "box": [round(x0), round(y0), round(x1 - x0), round(y1 - y0)],
                         "conf": min(w["conf"] for w in part)})
    hits.sort(key=lambda h: (-h["score"], -(h["text"].lower() == q), -h["conf"]))
    return {"query": text, "matches": hits}


# ---------------------------------------------------------------- motion

def watch(target="screen", frames=6, interval_ms=500, max_width=1568, cols=None):
    """Capture a burst of frames and tile them into one labelled contact sheet (see motion in games)."""
    _need_pil()
    frames = max(2, min(int(frames), 16))
    caps = []
    t0 = time.monotonic()
    for i in range(frames):
        img, origin, logical, info = capture(target)
        caps.append((round((time.monotonic() - t0) * 1000), img))
        if i + 1 < frames:
            time.sleep(max(0, interval_ms / 1000 - 0.01))
    cols = cols or (2 if frames <= 4 else 3 if frames <= 9 else 4)
    rows = (frames + cols - 1) // cols
    tw = max_width // cols
    th = round(caps[0][1].height * tw / caps[0][1].width)
    sheet = Image.new("RGB", (tw * cols, th * rows), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    font = _font(14)
    for i, (ms, img) in enumerate(caps):
        r, c = divmod(i, cols)
        sheet.paste(img.resize((tw, th), Image.LANCZOS), (c * tw, r * th))
        d.rectangle([c * tw, r * th, c * tw + 92, r * th + 20], fill=(0, 0, 0))
        d.text((c * tw + 4, r * th + 2), f"#{i + 1} {ms}ms", fill=(120, 200, 255), font=font)
    path = shot_dir() / f"watch-{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}.png"
    sheet.save(path)
    diffs = []
    for (_, a), (_, b) in zip(caps, caps[1:]):
        da = ImageChops.difference(a.resize((160, 90)), b.resize((160, 90)))
        diffs.append(round(sum(ImageStat.Stat(da).mean) / 3, 2))
    return {"path": str(path), "frames": frames, "interval_ms": interval_ms, "grid": [cols, rows],
            "motion_between_frames": diffs, "note": "contact sheet; frame coordinates are not clickable"}


def wait_stable(target="screen", timeout=10.0, threshold=0.6, settle_frames=2):
    """Block until the screen stops changing (e.g. after launching an app). Returns how long it took."""
    _need_pil()
    t0 = time.monotonic()
    prev, calm = None, 0
    while time.monotonic() - t0 < timeout:
        img = capture(target)[0].resize((192, 108))
        if prev is not None:
            diff = sum(ImageStat.Stat(ImageChops.difference(prev, img)).mean) / 3
            calm = calm + 1 if diff < threshold else 0
            if calm >= settle_frames:
                return {"stable": True, "seconds": round(time.monotonic() - t0, 2)}
        prev = img
        time.sleep(0.25)
    return {"stable": False, "seconds": round(time.monotonic() - t0, 2)}
