"""The pages of Arclight Settings.

Each page has a blocking `load()` (runs in a worker thread, talks to the daemons) and a
`build(data, ctx)` that turns the result into widgets on the GTK thread. `ctx` is the
window: ctx.row(setting) makes a registered generic row, ctx.apply(...) changes a setting,
ctx.toast(msg) reports, ctx.reload(page_id) rebuilds a page.
"""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from gi.repository import Adw, Gdk, GdkPixbuf, GLib, Gtk, Pango

from ... import __version__, identity
from . import backend as B
from .rows import fmt

REPO = Path(__file__).resolve().parents[4]
HOME = Path.home()


def human(n):
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def prefs_page():
    p = Adw.PreferencesPage()
    return p


def group(title=None, description=None):
    g = Adw.PreferencesGroup()
    if title:
        g.set_title(GLib.markup_escape_text(title))
    if description:
        g.set_description(GLib.markup_escape_text(description))
    return g


def screen_name(desc):
    """'Dell Inc. AW2725QF' -> 'Dell AW2725QF' (the maker's legal suffix is noise)."""
    import re
    return " ".join(re.sub(r",?\s*\b(Inc|Corp|Corporation|Co|Ltd|LLC)\b\.?", "", desc or "").split()).strip(" ,")


def gpu_name(raw):
    """'...: Advanced Micro Devices, Inc. [AMD/ATI] Strix [Radeon 880M / 890M]' -> 'AMD Radeon 880M / 890M'."""
    import re
    s = raw.split(": ", 1)[-1]
    low = s.lower()
    maker = next((v for k, v in (("advanced micro", "AMD"), ("amd", "AMD"), ("nvidia", "NVIDIA"), ("intel", "Intel"))
                  if k in low), "")
    brackets = [b for b in re.findall(r"\[([^\]]+)\]", s) if "/" not in b or " " in b]
    brackets = [b for b in brackets if b not in ("AMD/ATI",)]
    if brackets:
        name = brackets[-1]
        return name if not maker or name.startswith(maker) else f"{maker} {name}"
    return screen_name(s)


def info_row(title, value, mono=False, icon=None):
    r = Adw.ActionRow(title=GLib.markup_escape_text(str(title)))
    lab = Gtk.Label(label=str(value), xalign=1, ellipsize=Pango.EllipsizeMode.END, max_width_chars=48, selectable=True)
    lab.add_css_class("dim-label")
    if mono:   # numbers line up, but in the same font as every other row
        lab.add_css_class("numeric")
    r.add_suffix(lab)
    if icon:
        r.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return r


def settings_groups(page, settings, ctx, layout):
    """layout: [(group title, [keys...]), ...]; settings not named go into 'More'."""
    by = {s["key"]: s for s in settings}
    used = set()
    for title, keys in layout:
        rows = [by[k] for k in keys if k in by]
        if not rows:
            continue
        g = group(title)
        for s in rows:
            g.add(ctx.row(s))
            used.add(s["key"])
        page.add(g)
    rest = [s for s in settings if s["key"] not in used]
    if rest:
        g = group("More")
        for s in rest:
            g.add(ctx.row(s))
        page.add(g)


def list_settings(*prefixes):
    out = []
    for p in prefixes:
        out += B.call("settings.list", prefix=p)
    return out


# ---------------------------------------------------------------- base

class Page:
    id = ""
    title = ""
    icon = "emblem-system-symbolic"
    keywords = ""

    def load(self):
        return None

    def build(self, data, ctx):
        raise NotImplementedError


class PrefixPage(Page):
    """A page that is just settings with given prefixes, arranged by LAYOUT."""
    prefixes = ()
    layout = ()
    intro = None

    def load(self):
        return list_settings(*self.prefixes)

    def build(self, data, ctx):
        p = prefs_page()
        if self.intro:
            p.set_description(self.intro)
        if not data:
            g = group(None, "Nothing to show here on this machine.")
            p.add(g)
        settings_groups(p, data, ctx, self.layout or [(None, [s["key"] for s in data])])
        return p


# ---------------------------------------------------------------- appearance

THEME_DIRS = [HOME / ".config/theme/tokens", Path("/usr/share/arclight/theme"), Path("/usr/share/arclight/theme/tokens"),
              REPO / "desktop/overlay/.config/theme/tokens", REPO / "desktop/skel/.config/theme/tokens",
              Path("/etc/skel/.config/theme/tokens")]


def theme_tokens(slug):
    for d in THEME_DIRS:
        f = d / f"{slug}.json"
        if f.exists():
            try:
                return json.loads(f.read_text())
            except (OSError, ValueError):
                return None
    return None


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


class Appearance(Page):
    id, title, icon = "appearance", "Appearance", "preferences-desktop-appearance-symbolic"
    keywords = "theme glass blur gaps border rounding opacity glow shadow animation layout shell colours"
    LAYOUT = [
        ("Look", ["appearance.eclipse_look", "appearance.moving_light"]),
        ("Glass", ["appearance.opacity_active", "appearance.opacity_inactive", "appearance.blur",
                   "appearance.blur_size", "appearance.blur_passes", "appearance.blur_vibrancy",
                   "appearance.dim_inactive", "appearance.dim_strength"]),
        ("Shape", ["appearance.gaps_in", "appearance.gaps_out", "appearance.border_size", "appearance.rounding",
                   "appearance.active_border"]),
        ("Light and motion", ["appearance.glow", "appearance.shadow", "appearance.animations", "appearance.layout"]),
        ("Desktop shell", ["shell.current"]),
    ]

    def load(self):
        settings = list_settings("appearance", "shell")
        theme = next((s for s in settings if s["key"] == "appearance.theme"), None)
        tokens = {}
        for slug in (theme or {}).get("choices") or []:
            tokens[slug] = theme_tokens(slug)
        return {"settings": settings, "theme": theme, "tokens": tokens}

    def build(self, data, ctx):
        p = prefs_page()
        theme = data["theme"]
        if theme:
            g = group("Theme", "Changes the colours of every app at once.")
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=5,
                               min_children_per_line=2, column_spacing=10, row_spacing=10)
            cards = {}
            for slug in theme.get("choices") or []:
                tok = data["tokens"].get(slug)
                btn = Gtk.Button()
                btn.add_css_class("arc-theme-card")
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                swatch = Gtk.DrawingArea(content_height=64, content_width=150)
                cols = []
                if tok:
                    swatch.set_draw_func(self._draw_preview, tok)
                else:
                    cols = ["#0B0B0D", "#222327", "#6E4F36", "#D08A4E", "#EDB98A", "#FFC94A", "#FFE6B8"] \
                        if slug == "dynamic" else []
                    swatch.set_draw_func(self._draw_swatch, cols)
                box.append(swatch)
                name = (tok or {}).get("meta", {}).get("name", "From wallpaper" if slug == "dynamic" else slug)
                lab = Gtk.Label(label=name, xalign=0)
                lab.add_css_class("arc-theme-name")
                box.append(lab)
                btn.set_child(box)
                btn.set_tooltip_text((tok or {}).get("meta", {}).get("description",
                                     "Colours follow your wallpaper, kept warm" if slug == "dynamic" else slug))
                if slug == theme.get("value"):
                    btn.add_css_class("arc-selected")
                cards[slug] = btn

                def on_click(_b, slug=slug):
                    prev = next((s for s, c in cards.items() if c.has_css_class("arc-selected")), None)
                    for c in cards.values():
                        c.remove_css_class("arc-selected")
                    cards[slug].add_css_class("arc-selected")

                    def revert():
                        cards[slug].remove_css_class("arc-selected")
                        if prev:
                            cards[prev].add_css_class("arc-selected")
                    ctx.apply("appearance.theme", slug, revert, lambda r, n=name: ctx.toast(f"Theme: {n}", ok=True))
                btn.connect("clicked", on_click)
                flow.append(btn)
            ctx.theme_cards = cards
            g.add(flow)
            p.add(g)
        settings_groups(p, [s for s in data["settings"] if s["key"] != "appearance.theme"], ctx, self.LAYOUT)
        return p

    @staticmethod
    def _rounded(cr, x, y, w, h, r):
        import math
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()

    @classmethod
    def _draw_preview(cls, area, cr, w, h, tok):
        """A tiny desktop in the theme: night sky, the sun (glow ramp) with its corona, a glass pane with
        a lit top edge, an accent bar, and the focus ring in the theme's sun colour."""
        import math
        import cairo
        c, g = tok.get("color", {}), tok.get("glow", {})
        sun = tok.get("sun") or {"gold": c.get("accent", "#888888"), "gold-soft": c.get("accent-bright", "#aaaaaa")}

        def rgb(k, d="#333333"):
            try:
                return hex_rgb(k or d)
            except ValueError:
                return hex_rgb(d)
        cls._rounded(cr, 0, 0, w, h, 11)
        cr.clip()
        sky = cairo.LinearGradient(0, 0, 0, h)
        sky.add_color_stop_rgb(0, *rgb(c.get("surface")))
        sky.add_color_stop_rgb(1, *rgb(c.get("bg-base")))
        cr.set_source(sky)
        cr.paint()
        # the sun: corona from the glow ramp, a dark disc, a bright rim
        sx, sy, sr = w * 0.76, h * 0.36, h * 0.15
        cor = cairo.RadialGradient(sx, sy, sr * 0.9, sx, sy, sr * 2.6)
        cor.add_color_stop_rgba(0, *rgb(g.get("mid") or sun.get("gold")), 0.95)
        cor.add_color_stop_rgba(0.35, *rgb(g.get("base") or sun.get("gold")), 0.45)
        cor.add_color_stop_rgba(1, *rgb(g.get("base") or sun.get("gold")), 0.0)
        cr.set_source(cor)
        cr.arc(sx, sy, sr * 2.6, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(*rgb(c.get("bg-base")))
        cr.arc(sx, sy, sr, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(*rgb(sun.get("gold-soft")), 0.95)
        cr.set_line_width(1.2)
        cr.arc(sx, sy, sr, 0, 2 * math.pi)
        cr.stroke()
        # a glass pane: translucent raised surface, lit top edge, focus ring in the sun colour
        px, py, pw, ph = w * 0.07, h * 0.44, w * 0.56, h * 0.62
        cls._rounded(cr, px, py, pw, ph, 7)
        cr.set_source_rgba(*rgb(c.get("surface-raised")), 0.72)
        cr.fill_preserve()
        ring = cairo.LinearGradient(px, py, px + pw, py + ph)
        ring.add_color_stop_rgba(0, *rgb(sun.get("gold-soft")), 1.0)
        ring.add_color_stop_rgba(0.45, *rgb(sun.get("gold")), 0.8)
        ring.add_color_stop_rgba(1, *rgb(c.get("accent-dim")), 0.6)
        cr.set_source(ring)
        cr.set_line_width(1.4)
        cr.stroke()
        cr.set_source_rgba(1, 1, 1, 0.35)
        cr.set_line_width(1)
        cr.move_to(px + 7, py + 1.5)
        cr.line_to(px + pw - 7, py + 1.5)
        cr.stroke()
        # text lines + an accent bar inside the pane
        for i, (k, frac, a) in enumerate((("text-primary", 0.62, 0.9), ("text-secondary", 0.44, 0.8))):
            cr.set_source_rgba(*rgb(c.get(k)), a)
            cls._rounded(cr, px + 8, py + 8 + i * 7, pw * frac, 3, 1.5)
            cr.fill()
        cr.set_source_rgb(*rgb(c.get("accent")))
        cls._rounded(cr, px + 8, py + 25, pw * 0.3, 4, 2)
        cr.fill()
        cr.set_source_rgb(*rgb(c.get("error")))
        cr.arc(px + pw - 9, py + 9, 2.4, 0, 2 * math.pi)
        cr.fill()

    @classmethod
    def _draw_swatch(cls, area, cr, w, h, cols):
        cls._rounded(cr, 0, 0, w, h, 11)
        cr.clip()
        if not cols:
            cr.set_source_rgb(0.1, 0.12, 0.18)
            cr.paint()
            return
        n = len(cols)
        for i, c in enumerate(cols):
            try:
                cr.set_source_rgb(*hex_rgb(c))
            except ValueError:
                continue
            cr.rectangle(i * w / n, 0, w / n + 1, h)
            cr.fill()


# ---------------------------------------------------------------- wallpaper

THUMBS = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "arclight/thumbs"


def wall_name(fname):
    """'arclight-eclipse-crescent.jpg' -> 'Eclipse crescent' (file names stay in the tooltip)."""
    stem = os.path.splitext(os.path.basename(str(fname)))[0]
    for pre in ("arclight-", "eclipse-os-"):
        if stem.startswith(pre) and len(stem) > len(pre):
            stem = stem[len(pre):]
    import re
    words = stem.replace("_", " ").replace("-", " ").strip()
    words = re.sub(r"\s+(\d{3,4}p?|\d{3,5}x\d{3,5}|[48]k)$", "", words, flags=re.I) or words   # 'Eclipse 1080' -> 'Eclipse'
    return (words[:1].upper() + words[1:]) if words else str(fname)


def snap_words(label):
    """'before pkg install btop' -> 'Before installing btop' (daemon labels are short and technical)."""
    import re
    m = re.match(r"before pkg (install|remove|upgrade|update)\b\s*(.*)", label or "")
    if not m:
        return (label[:1].upper() + label[1:]) if label else label
    verb = {"install": "installing", "remove": "removing", "upgrade": "updating", "update": "updating"}[m.group(1)]
    what = m.group(2).strip() or ("everything" if verb == "updating" else "apps")
    return f"Before {verb} {what}"


def thumbnail(path, size=240):
    """Cached PNG thumbnail path for an image (made in a worker thread)."""
    st = os.stat(path)
    h = hashlib.sha1(f"{path}:{st.st_mtime_ns}:{st.st_size}:{size}".encode()).hexdigest()[:20]
    out = THUMBS / f"{h}.png"
    if not out.exists():
        THUMBS.mkdir(parents=True, exist_ok=True)
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), size, -1, True)
        tmp = out.with_suffix(".tmp")
        pb.savev(str(tmp), "png", [], [])
        os.replace(tmp, out)
    return str(out)


def living_group(setting, cur_name, ctx):
    """Living wallpaper: on/off + a strip of the day (Night, Dawn, Midday, Dusk, Now)."""
    from ... import livingwall as LW
    eclipse = LW.is_eclipse(cur_name)
    lg = group("Living wallpaper", "The eclipse photo slowly changes with the time of day. It stays still on "
               "battery and in Totality." if eclipse else "Works with the Eclipse photo. Pick it below to use it.")
    lg.add(ctx.row(setting))
    strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True, margin_top=10)
    pics = []
    for label in ("Night", "Dawn", "Midday", "Dusk", "Now"):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, width_request=120, height_request=68)
        pic.add_css_class("arc-wall")
        box.append(pic)
        lab = Gtk.Label(label=label)
        lab.add_css_class("arc-wall-name" if label != "Now" else "heading")
        box.append(lab)
        strip.append(box)
        pics.append(pic)
    lg.add(strip)

    def got(items):
        for pic, (_label, path) in zip(pics, items):
            pic.set_filename(path)
    B.run_async(lambda: LW.thumbs((320, 180)), got, lambda e: strip.set_visible(False))
    return lg


class Wallpaper(Page):
    id, title, icon = "wallpaper", "Wallpaper", "preferences-desktop-wallpaper-symbolic"
    keywords = "background image picture wallpaper switcher"

    def load(self):
        cur = B.call("settings.get", key="wallpaper.current")
        folder = B.call("settings.get", key="wallpaper.folder").get("value")
        try:
            theme = B.call("settings.get", key="appearance.theme")
        except Exception:
            theme = None
        try:
            living = B.call("settings.get", key="wallpaper.living")
        except Exception:
            living = None
        return {"current": cur, "folder": folder, "theme": theme, "living": living}

    def build(self, data, ctx):
        p = prefs_page()
        cur = data["current"]
        folder = Path(data["folder"] or HOME / "Pictures/wallpapers")
        choices = cur.get("choices") or []
        current = cur.get("value") or ""
        cur_name = os.path.basename(str(current).rstrip("/"))

        hero_g = group("Current wallpaper")
        hero = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, height_request=270)
        hero.add_css_class("arc-hero")
        hero_g.add(hero)
        name = Gtk.Label(label=wall_name(cur_name) if cur_name else "None yet", xalign=0, margin_top=8)
        name.add_css_class("dim-label")
        hero_g.add(name)
        p.add(hero_g)

        def show_hero(path):
            if path and os.path.exists(path):
                B.run_async(lambda: thumbnail(path, 1100), lambda t: hero.set_filename(t))
        show_hero(current if os.path.isabs(str(current)) else str(folder / current))
        if data.get("living"):
            p.add(living_group(data["living"], cur_name, ctx))

        g = group("Wallpapers", "Click one to use it. Super+W opens the quick picker.")
        theme = data.get("theme") or {}
        if "dynamic" in (theme.get("choices") or []):
            btn = Gtk.Button(label="Colours from wallpaper", valign=Gtk.Align.CENTER)
            btn.add_css_class("pill")
            btn.connect("clicked", lambda _b: ctx.apply("appearance.theme", "dynamic", lambda: None,
                                                        lambda r: ctx.toast("Colours now follow the wallpaper", ok=True)))
            g.set_header_suffix(btn)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=6,
                           min_children_per_line=2, column_spacing=12, row_spacing=12)
        tiles = {}
        for fname in choices:
            full = str(folder / fname)
            btn = Gtk.Button()
            btn.add_css_class("arc-wall")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, width_request=172, height_request=97)
            box.append(pic)
            lab = Gtk.Label(label=wall_name(fname), ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
            lab.add_css_class("arc-wall-name")
            box.append(lab)
            btn.set_child(box)
            btn.set_tooltip_text(full)
            if fname == cur_name:
                btn.add_css_class("arc-selected")
            tiles[fname] = btn
            if os.path.exists(full):
                B.run_async(lambda full=full: thumbnail(full), lambda t, pic=pic: pic.set_filename(t),
                            lambda e, lab=lab: lab.set_label(f"{lab.get_label()} (can't open)"))

            def on_click(_b, fname=fname, full=full):
                prev = next((f for f, b in tiles.items() if b.has_css_class("arc-selected")), None)
                for b in tiles.values():
                    b.remove_css_class("arc-selected")
                tiles[fname].add_css_class("arc-selected")

                def revert():
                    tiles[fname].remove_css_class("arc-selected")
                    if prev:
                        tiles[prev].add_css_class("arc-selected")

                def ok(_r):
                    name.set_label(wall_name(fname))
                    show_hero(full)
                ctx.apply("wallpaper.current", fname, revert, ok)
            btn.connect("clicked", on_click)
            flow.append(btn)
        ctx.wall_tiles = tiles
        if not choices:
            g.set_description(GLib.markup_escape_text(f"No pictures yet. Put JPG or PNG files in {folder}."))
        g.add(flow)
        p.add(g)
        return p


# ---------------------------------------------------------------- simple setting pages

class Displays(Page):
    id, title, icon = "displays", "Displays", "video-display-symbolic"
    keywords = "monitor screen resolution refresh scale vrr tearing brightness cursor"

    def load(self):
        return {"monitors": B.call("mon.list"), "settings": list_settings("display", "cursor")}

    def build(self, data, ctx):
        p = prefs_page()
        for m in data["monitors"]:
            mirror = m.get("mirrorOf")
            title = screen_name(m.get("description")) or m["name"]
            g = group(title)
            g.add(info_row("Resolution", f"{m['width']} × {m['height']}  ·  {m.get('refreshRate', 0):.0f} Hz", mono=True))
            g.add(info_row("Position", f"{m.get('x', 0)}, {m.get('y', 0)}", mono=True))
            g.add(info_row("Scale", fmt(m.get("scale"), {})))
            if mirror and mirror not in ("none", "0", None):
                g.add(info_row("Shows the same as", mirror))
            g.add(info_row("Workspace", m.get("workspace", "?")))
            where = f"Plugged into {m['name']}"
            if m.get("focused") and len(data["monitors"]) > 1:
                where += ". The screen you are using now"
            g.set_description(where)
            p.add(g)
        settings_groups(p, data["settings"], ctx, [("Options", [s["key"] for s in data["settings"]])])
        return p


class Input(PrefixPage):
    id, title, icon = "input", "Input", "input-keyboard-symbolic"
    keywords = "keyboard layout mouse speed acceleration touchpad scroll repeat focus"
    prefixes = ("input",)
    layout = [("Keyboard", ["input.keyboard_layout", "input.keyboard_options", "input.repeat_rate", "input.repeat_delay"]),
              ("Mouse and touchpad", ["input.mouse_speed", "input.mouse_accel", "input.natural_scroll", "input.follow_mouse"])]


class Sound(PrefixPage):
    id, title, icon = "sound", "Sound", "audio-volume-high-symbolic"
    keywords = "audio volume mute speakers microphone output device"
    prefixes = ("audio",)
    layout = [("Output", ["audio.output", "audio.volume", "audio.muted"]),
              ("Microphone", ["audio.mic_volume", "audio.mic_muted"])]


class Network(PrefixPage):
    id, title, icon = "network", "Network & Bluetooth", "network-wireless-symbolic"
    keywords = "wifi wireless ethernet internet bluetooth radio"
    prefixes = ("network", "bluetooth")
    layout = [("Network", ["network.networking", "network.wifi"]), ("Bluetooth", ["bluetooth.enabled"])]


class Power(PrefixPage):
    id, title, icon = "power", "Power & Idle", "battery-full-charged-symbolic"
    keywords = "power profile performance battery idle lock screen off sleep"
    prefixes = ("power", "idle")
    layout = [("Power", ["power.profile"]), ("Idle", ["idle.lock_after", "idle.screen_off_after"])]


# ---------------------------------------------------------------- searchable lists

class SearchList(Page):
    placeholder = "Search"

    def rows(self, data):
        raise NotImplementedError

    def build(self, data, ctx):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                      margin_start=24, margin_end=24)
        clamp = Adw.Clamp(maximum_size=860, child=box)
        entry = Gtk.SearchEntry(placeholder_text=self.placeholder)
        box.append(entry)
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lb.add_css_class("boxed-list")
        items = []
        for row, hay in self.rows(data):
            lb.append(row)
            items.append((row, hay.lower()))
        count = Gtk.Label(xalign=0)
        count.add_css_class("dim-label")
        box.append(count)
        box.append(lb)

        def refilter(*_a):
            q = entry.get_text().lower().strip()
            n = 0
            for row, hay in items:
                vis = not q or all(w in hay for w in q.split())
                row.set_visible(vis)
                n += vis
            count.set_label(f"{n} of {len(items)}" if q else f"{len(items)} in all")
        entry.connect("search-changed", refilter)
        refilter()
        sw = Gtk.ScrolledWindow(child=clamp, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.arc_search_entry = entry
        return sw


class Keybinds(SearchList):
    id, title, icon = "keybinds", "Keybinds", "preferences-desktop-keyboard-shortcuts-symbolic"
    keywords = "keys shortcuts binds hotkeys"
    placeholder = "Search keys, like terminal, workspace or super"

    def load(self):
        return B.call("binds.list")

    KEYS = {"SUPER": "Super", "CTRL": "Ctrl", "ALT": "Alt", "SHIFT": "Shift", "return": "Enter", "escape": "Esc",
            "space": "Space", "tab": "Tab", "print": "Print", "left": "←", "right": "→", "up": "↑", "down": "↓",
            "mouse:272": "Left click", "mouse:273": "Right click", "mouse_down": "Scroll down", "mouse_up": "Scroll up",
            "xf86audioraisevolume": "Volume up key", "xf86audiolowervolume": "Volume down key",
            "xf86audiomute": "Mute key", "xf86audiomicmute": "Mic mute key", "xf86monbrightnessup": "Brightness up key",
            "xf86monbrightnessdown": "Brightness down key", "xf86audionext": "Next key", "xf86audioprev": "Previous key",
            "xf86audioplay": "Play key", "xf86audiopause": "Pause key"}

    # what a bind does, in words, for binds that have no description (most of them)
    WORDS = [("hyprlock", "Lock the screen"), ("shellctl launcher", "Open the app launcher"),
             ("shellctl wallpaper", "Pick a wallpaper"), ("shellctl overview", "Show all windows"),
             ("shellctl", "Desktop shell"), ("arclight-stop", "Stop what the AI is doing"), ("arclight-ask --voice", "Ask by voice"),
             ("arclight-ask --selection", "Ask about the selected text"), ("arclight-ask", "Ask"),
             ("arclight-settings", "Settings"), ("arclight-store", "Eclipse Store"),
             ("totality", "Totality (game mode)"), ("shot region", "Screenshot of an area"),
             ("shot", "Screenshot"), ("grim", "Screenshot"), ("ghostty", "Open the terminal"),
             ("kitty", "Open the terminal"), ("alacritty", "Open the terminal"), ("foot", "Open the terminal"),
             ("thunar", "Open files"), ("nautilus", "Open files"), ("dolphin", "Open files"),
             ("zen-browser", "Open the web browser"), ("firefox", "Open the web browser"),
             ("chromium", "Open the web browser"), ("zeditor", "Open Zed"), ("code", "Open VS Code"),
             ("wpctl", "Volume"), ("pactl", "Volume"), ("brightnessctl", "Brightness"), ("playerctl", "Media")]
    DISPATCH = {"window.close": "Close the window", "killactive": "Close the window",
                "window.fullscreen": "Full screen", "fullscreen": "Full screen",
                "window.float": "Float the window", "togglefloating": "Float the window",
                "window.pseudo": "Pseudo-tile the window", "layout.togglesplit": "Flip the split",
                "togglesplit": "Flip the split", "exit": "Log out", "window.move": "Move the window",
                "window.resize": "Resize the window", "movewindow": "Move the window",
                "resizewindow": "Resize the window", "window.pin": "Pin the window"}

    @classmethod
    def describe(cls, b):
        """Plain words for one bind: its description, else a guess from the command, else the command."""
        if b.get("description"):
            return b["description"]
        disp, arg = str(b.get("dispatcher") or ""), str(b.get("arg") or "").strip()
        if disp == "__lua":
            return ""
        if disp in ("exec", "hl.dsp.exec_cmd", "exec_cmd"):
            low = arg.lower()
            if "eclipse-ai-toggle" in low:      # Super+A: Eclipse AI, or Claude Code in the core edition
                from arclight.edition import has_ai
                return "Open Eclipse AI" if has_ai() else "Open Claude Code"
            for k, words in cls.WORDS:
                if k in low:
                    return words
            prog = os.path.basename(arg.split()[0]) if arg else "?"
            return f"Run {prog}"
        short = disp.removeprefix("hl.dsp.")
        if short in cls.DISPATCH:
            return cls.DISPATCH[short]
        parts = arg.split()
        if short in ("focus", "workspace") and parts[:1] == ["workspace"] and len(parts) > 1:
            return f"Go to workspace {parts[1]}"
        if short == "workspace" and parts:
            return f"Go to workspace {parts[0]}"
        if "movetoworkspace" in short or (short == "window.move" and parts[:1] == ["workspace"]):
            return f"Move the window to workspace {parts[-1]}" if parts else "Move the window to a workspace"
        if short in ("focus", "movefocus") and parts:
            return f"Focus {' '.join(parts)}"
        return f"{short.replace('.', ' ').replace('_', ' ').capitalize()} {arg}".strip()

    @classmethod
    def pretty(cls, combo):
        parts = [p.strip() for p in str(combo).split("+") if p.strip()]
        return " + ".join(cls.KEYS.get(p, cls.KEYS.get(p.lower(), p.upper() if len(p) == 1 else p)) for p in parts)

    def rows(self, data):
        # one row per action, with every key that does it (Super+Q, Super+Enter and Ctrl+Alt+T all open the terminal)
        groups = {}
        for i, b in enumerate(data):
            what = self.describe(b)
            groups.setdefault(what or f"__{i}", []).append(b)
        for what, binds in groups.items():
            title = "Custom action" if what.startswith("__") else what
            r = Adw.ActionRow(title=GLib.markup_escape_text(title))
            raw = sorted({f"{b.get('dispatcher', '')} {b.get('arg', '')}".strip() for b in binds})
            r.set_tooltip_text("\n".join(raw))     # the exact command, for the curious
            caps = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            for b in binds[:3]:
                cap = Gtk.Label(label=self.pretty(b.get("combo", "?")), valign=Gtk.Align.CENTER)
                cap.add_css_class("arc-keycap")
                caps.append(cap)
            if len(binds) > 3:
                more = Gtk.Label(label=f"+{len(binds) - 3}")
                more.add_css_class("dim-label")
                caps.append(more)
            r.add_suffix(caps)
            r.add_css_class("arc-row")
            combos = " ".join(f"{b.get('combo')} {self.pretty(b.get('combo', ''))}" for b in binds)
            yield r, f"{combos} {title} {' '.join(raw)}"


class Apps(SearchList):
    id, title, icon = "apps", "Apps", "view-app-grid-symbolic"
    keywords = "applications programs installed launch"
    placeholder = "Search installed apps"

    def load(self):
        return B.call("app.list")

    def rows(self, data):
        for a in data:
            r = Adw.ActionRow(title=GLib.markup_escape_text(a.get("name", "?")),
                              subtitle=GLib.markup_escape_text(a.get("comment") or ""))
            r.set_tooltip_text(a.get("id", ""))
            ic = a.get("icon") or a.get("id") or ""
            if ic.startswith("/") and os.path.exists(ic):
                icon = Gtk.Image.new_from_file(ic)
            else:
                theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
                icon = Gtk.Image.new_from_icon_name(ic if ic and theme.has_icon(ic) else "application-x-executable")
            icon.set_pixel_size(32)
            r.add_prefix(icon)
            yield r, f"{a.get('name')} {a.get('id')} {a.get('comment')} {' '.join(a.get('categories') or [])}"


# ---------------------------------------------------------------- system

class System(Page):
    id, title, icon = "system", "System", "computer-symbolic"
    keywords = "hostname timezone locale language swappiness updates upgrade packages snapshots"

    def load(self):
        out = {"settings": list_settings("system"), "info": B.call("sys.info")}
        try:
            out["updates"] = B.call("pkg.list", upgradable=True)
        except Exception as e:
            out["updates_error"] = B.message(e)
        try:
            out["snaps"] = B.call("snap.list")
        except Exception as e:
            out["snaps"] = {"supported": False, "snapshots": [], "error": B.message(e)}
        return out

    def build(self, data, ctx):
        p = prefs_page()
        settings_groups(p, data["settings"], ctx, [
            ("This computer", ["system.hostname", "system.timezone", "system.ntp", "system.locale"]),
            ("Safety and memory", ["system.auto_snapshot", "system.swappiness"])])
        i = data["info"]
        g = group("Overview")
        up = int(i.get("uptime_s", 0))
        g.add(info_row("Operating system", i.get("os") or i.get("name") or "?"))
        g.add(info_row("Kernel", i.get("kernel", "?"), mono=True))
        g.add(info_row("Uptime", f"{up // 86400}d {up % 86400 // 3600}h {up % 3600 // 60}m" if up >= 86400 else
                       f"{up // 3600}h {up % 3600 // 60}m"))
        mem = i.get("memory") or {}
        if mem.get("total"):
            g.add(info_row("Memory", f"{human(mem['total'] - mem.get('available', 0))} used of {human(mem['total'])}"))
        for d in i.get("disks", []):
            g.add(info_row("Disk" if d["mount"] == "/" else f"Disk {d['mount']}",
                           f"{human(d['used'])} used of {human(d['size'])}"))
        if i.get("failed_units"):
            g.add(info_row("Broken services", ", ".join(i["failed_units"]), icon="dialog-warning-symbolic"))
        p.add(g)

        ups = data.get("updates")
        ug = group("Updates", data.get("updates_error") or
                   (f"{len(ups)} update{'s' if len(ups) != 1 else ''} ready." if ups else "Everything is up to date."))
        btn = Gtk.Button(label="Update now", valign=Gtk.Align.CENTER)
        btn.add_css_class("suggested-action")
        btn.set_sensitive(bool(ups))
        spinner = Adw.Spinner(visible=False, valign=Gtk.Align.CENTER)
        hb = Gtk.Box(spacing=8)
        hb.append(spinner)
        hb.append(btn)
        ug.set_header_suffix(hb)
        for u in (ups or [])[:60]:
            ug.add(info_row(u["name"], f"{u['version']}  →  {u['new_version']}", mono=True))
        if ups and len(ups) > 60:
            ug.add(info_row("…", f"{len(ups) - 60} more"))
        ctx.update_button = btn

        def do_upgrade(_b):
            dlg = Adw.AlertDialog(heading="Update everything?",
                                  body=f"{len(ups or [])} apps and system parts get their newer versions. "
                                       "A restore point is made first when this PC supports it.")
            dlg.add_response("cancel", "Not now")
            dlg.add_response("update", "Update")
            dlg.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)
            dlg.set_default_response("update")

            def on_resp(_d, resp):
                if resp != "update":
                    return
                ctx.start_upgrade(btn, spinner)
            dlg.connect("response", on_resp)
            dlg.present(ctx)
        btn.connect("clicked", do_upgrade)
        p.add(ug)

        sn = data.get("snaps") or {}
        sg = group("Restore points", "Made by themselves before every update." if sn.get("supported") else
                   "Restore points need a whole-disk install.")
        for s in (sn.get("snapshots") or [])[:20]:
            when = time.strftime("%a %d %b, %H:%M", time.localtime(s["time"])) if s.get("time") else ""
            sg.add(info_row(snap_words(s.get("label")) or s["id"], when or s["id"]))
        p.add(sg)
        return p


# ---------------------------------------------------------------- AI

WHO = {"claude": "Claude", "codex": "Codex", "ask": "Ask", "human": "You", "user": "You", "arc": "You (arc)",
       "settings": "You (Settings)", "store": "You (Store)"}
METHOD_WORDS = {
    "settings.set": "Changed {key}", "settings.reset": "Put {key} back", "file.write": "Changed a file",
    "file.edit": "Edited a file", "file.delete": "Deleted a file", "file.move": "Moved a file",
    "file.revert": "Undid a file change", "pkg.install": "Installed {names}", "pkg.remove": "Removed {names}",
    "pkg.upgrade": "Updated the system", "svc.restart": "Restarted {name}", "svc.start": "Started {name}",
    "svc.stop": "Stopped {name}", "svc.enable": "Turned on {name}", "svc.disable": "Turned off {name}",
    "input.click": "Clicked", "input.type": "Typed text", "input.key": "Pressed keys", "app.launch": "Opened {name}",
    "exec": "Ran a command", "snap.create": "Made a restore point", "snap.rollback": "Went back to a restore point",
    "file.copy": "Copied a file", "file.mkdir": "Made a folder", "file.chmod": "Changed file permissions",
    "sys.hostname": "Renamed the computer", "sys.timezone": "Changed the time zone", "sys.locale": "Changed the language",
    "sys.power": "Power action", "win.close": "Closed a window", "win.focus": "Switched window",
    "ws.switch": "Switched workspace", "game.launch": "Started a game", "game.mode": "Totality", "totality.mode": "Totality",
    "input.scroll": "Scrolled", "input.drag": "Dragged", "ui.press": "Pressed a button", "ui.set_text": "Filled in text",
    "notify.send": "Sent a notification", "clip.set": "Copied to the clipboard",
}
SVC_WORDS = {"restart": "Restarted", "start": "Started", "stop": "Stopped", "enable": "Turned on",
             "disable": "Turned off", "reload": "Reloaded"}


def action_words(a):
    """One plain line for a logged action: 'Changed appearance.gaps_in', 'Installed krita'."""
    m, prm = a.get("method", "?"), a.get("params") or {}
    if m == "svc.action":
        unit = str(prm.get("unit") or prm.get("name") or "a service").removesuffix(".service")
        return f"{SVC_WORDS.get(prm.get('action'), 'Changed')} {unit}"
    w = METHOD_WORDS.get(m)
    if not w:
        return m
    names = prm.get("names") or prm.get("name") or ""
    if isinstance(names, list):
        names = ", ".join(map(str, names[:3]))
    key = prm.get("key", "a setting")
    try:
        from .rows import FRIENDLY
        key = FRIENDLY.get(key, (key,))[0].lower() if key in FRIENDLY else key
    except Exception:
        pass
    return w.format(key=key, names=names or "an app", name=prm.get("name") or prm.get("unit") or "an app")


def _routine_when(r):
    """'daily 09:00' + 'Sun 2026-10-11 09:00:24 EDT' -> 'Every day at 09:00 · next: Sun 11 Oct, 09:00'."""
    import re as _re
    sch = (r.get("schedule") or "").strip()
    m = _re.fullmatch(r"(daily|every day|weekdays|weekends?|mon|tue|wed|thu|fri|sat|sun)\w*\s+(\d{1,2}:\d{2})", sch.lower())
    if m:
        day = {"daily": "Every day", "every day": "Every day", "weekdays": "Weekdays", "weekend": "Weekends",
               "weekends": "Weekends"}.get(m[1], "Every " + {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
                                                             "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
                                                             "sun": "Sunday"}.get(m[1], m[1]))
        sch = f"{day} at {m[2]}"
    elif _re.fullmatch(r"every\s+\d+\s*h.*", sch.lower()):
        sch = "Every " + _re.sub(r"\s*h.*", " hours", sch.lower().split("every", 1)[1].strip())
    if not r.get("enabled", True):
        return f"{sch} \u00b7 off"
    nxt = r.get("next") or ""
    n = _re.match(r"(\w{3}) (\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2})", nxt)
    if n:
        months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        nxt = f"{n[1]} {int(n[4])} {months[int(n[3]) - 1]}, {n[5]}"
    return f"{sch} \u00b7 next: {nxt}" if nxt else sch


class AI(Page):
    id, title, icon = "ai", "AI", "weather-storm-symbolic"
    keywords = "ai agent claude codex autofix indicator voice actions history mcp"

    def load(self):
        out = {"system_up": B.ping("system"), "session_up": B.ping("session")}
        out["settings"] = list_settings("ai") if out["session_up"] else []
        try:
            out["actions"] = B.call("actions.tail", n=30) if out["system_up"] else []
        except Exception as e:
            out["actions"], out["actions_error"] = [], B.message(e)
        try:  # desktop side: settings changes, clicks, typing
            if out["session_up"]:
                out["actions"] = sorted(out["actions"] + B.call("session.actions", n=30), key=lambda a: a.get("time", 0))[-40:]
        except Exception:
            pass
        try:
            out["file_history"] = B.call("file.history", limit=20) if out["system_up"] else []
        except Exception:
            out["file_history"] = []
        try:
            from arclight import routines as RT
            out["routines"] = RT.listing()
        except Exception:
            out["routines"] = []
        return out

    def build(self, data, ctx):
        from arclight.edition import has_ai
        core = not has_ai()
        p = prefs_page()
        if core:
            p.set_description("Claude Code can run this whole PC through two helpers (open a terminal and type "
                              "claude). Everything it does is listed here, and most of it can be undone.")
        else:
            p.set_description("The AI (Ask, Claude Code, Codex) changes this PC through two helpers. "
                              "Everything it does is listed here, and most of it can be undone.")
        st = group("Helpers")
        for label, up, what, unit in (
                ("System helper", data["system_up"], "Apps, services, files and system settings", "arclightd"),
                ("Desktop helper", data["session_up"], "Sees the screen, uses mouse and keyboard, desktop settings",
                 "arclight-session")):
            r = Adw.ActionRow(title=label, subtitle=what)
            r.add_css_class("arc-row")
            r.set_tooltip_text(unit)
            dot = Gtk.Label(label="● On" if up else "● Off")
            dot.add_css_class("arc-dot-ok" if up else "arc-dot-bad")
            r.add_suffix(dot)
            st.add(r)
        p.add(st)
        if core:
            # the built-in AI's own settings (Ask, Fix with AI, local models) do nothing in this edition: hide them
            keep = [dict(s, arc_title="Show a banner while Claude Code uses the mouse") if s["key"] == "ai.indicator"
                    else s for s in data["settings"] if s["key"] in ("ai.indicator", "ai.auto_game_mode")]
            settings_groups(p, keep, ctx, [("While Claude Code works", ["ai.indicator"]),
                                           ("Games", ["ai.auto_game_mode"])])
        else:
            settings_groups(p, data["settings"], ctx, [("Use the AI", ["ai.enabled"]),
                                                       ("The AI", ["ai.agent", "ai.ask_model", "ai.voice"]),
                                                       ("What it does by itself", ["ai.autofix", "ai.notify_failures",
                                                                                   "ai.indicator", "ai.auto_game_mode"])])
        rg = group("Routines", "Things the AI does by itself on a schedule. To make one, just ask: "
                               "\u201cevery morning at 9, update the system and tell me what changed\u201d.")
        add = Gtk.Button(label="New routine", valign=Gtk.Align.CENTER)
        add.add_css_class("pill")
        add.connect("clicked", lambda _b: subprocess.Popen(
            ["arclight-ask", "--prefill", "Make a routine: every "], start_new_session=True))
        rg.set_header_suffix(add)
        if not data.get("routines"):
            rg.add(info_row("No routines yet", "They show up here, with when they run next."))
        for r in data.get("routines") or []:
            row = Adw.ActionRow(title=GLib.markup_escape_text(r.get("name", r["id"])),
                                subtitle=GLib.markup_escape_text(_routine_when(r)))
            row.set_tooltip_text(r.get("prompt", ""))
            row.add_css_class("arc-row")
            sw = Gtk.Switch(active=r.get("enabled", True), valign=Gtk.Align.CENTER)
            sw.set_tooltip_text("On / off")
            sw.connect("notify::active", lambda w, _p, rid=r["id"]: subprocess.Popen(
                ["arclight-routine", "enable" if w.get_active() else "disable", rid], start_new_session=True))
            row.add_suffix(sw)
            run = Gtk.Button(label="Run now", valign=Gtk.Align.CENTER)
            run.add_css_class("pill")

            def run_now(b, rid=r["id"]):
                subprocess.Popen(["arclight-routine", "run", rid], start_new_session=True)
                b.set_label("Running\u2026")
                b.set_sensitive(False)
                ctx.toast("Running now. A notification shows the result.", ok=True)
            run.connect("clicked", run_now)
            row.add_suffix(run)
            rm = Gtk.Button(label="Remove", valign=Gtk.Align.CENTER)
            rm.add_css_class("pill")
            rm.connect("clicked", lambda b, rid=r["id"], rw=row: (
                subprocess.run(["arclight-routine", "remove", rid], capture_output=True), rw.set_visible(False),
                ctx.toast("Routine removed", ok=True)))
            row.add_suffix(rm)
            rg.add(row)
        if not core:
            p.add(rg)
        ag = group("Recent changes", data.get("actions_error") or
                   f"What {'Claude Code' if core else 'the AI'} (and you) changed lately. Newest first.")
        acts = list(reversed(data.get("actions") or []))
        if not acts:
            ag.add(info_row("Nothing yet", ""))
        for a in acts[:30]:
            when = time.strftime("%a %d %b, %H:%M", time.localtime(a.get("time", 0)))
            r = Adw.ActionRow(title=GLib.markup_escape_text(action_words(a)),
                              subtitle=GLib.markup_escape_text(f"{when} · {WHO.get(a.get('agent'), a.get('agent') or 'someone')}"))
            r.set_tooltip_text(f"{a.get('method', '?')} {json.dumps(a.get('params') or {}, ensure_ascii=False)[:300]}")
            r.add_css_class("arc-row")
            ok = a.get("ok", True)
            lab = Gtk.Label(label="Done" if ok else "Failed")
            lab.add_css_class("arc-dot-ok" if ok else "arc-dot-bad")
            if not ok and a.get("error"):
                lab.set_tooltip_text(a["error"])
            key = (a.get("params") or {}).get("key")
            if ok and a.get("method") == "settings.set" and key:   # button first: Done / Failed stay in one column
                r.add_suffix(self._undo_button("Reset to mine", f"{key} is back to your own config",
                                               lambda key=key: B.call("settings.reset", key=key), ctx))
            r.add_suffix(lab)
            icon = {"claude": "starred-symbolic", "codex": "utilities-terminal-symbolic"}.get(a.get("agent"), "avatar-default-symbolic")
            r.add_prefix(Gtk.Image.new_from_icon_name(icon))
            ag.add(r)
        p.add(ag)
        ug = group("Undo file changes", "The old version of every changed file is kept. "
                                        "Undo puts it back (and keeps the new one, so you can change your mind).")
        hist = data.get("file_history") or []
        if not hist:
            ug.add(info_row("No file changes yet", ""))
        home = str(Path.home())
        for h in hist:
            when = time.strftime("%a %d %b, %H:%M", time.localtime(h.get("time", 0)))
            path = h.get("path", "?")
            short = "~" + path[len(home):] if path.startswith(home) else path
            what = {"write": "changed", "edit": "edited", "delete": "deleted", "move": "moved", "chmod": "permissions",
                    "revert": "undone"}.get(h.get("op"), h.get("op", ""))
            sub = f"{when} · {what}" + (f" · {h['note']}" if h.get("note") else "") + \
                  ("" if h.get("existed", True) else " · was new")
            r = Adw.ActionRow(title=GLib.markup_escape_text(short), subtitle=GLib.markup_escape_text(sub))
            r.add_css_class("arc-row")
            r.add_suffix(self._undo_button("Undo", f"Restored {short}",
                                           lambda hid=h["id"]: B.call("file.revert", history_id=hid), ctx))
            ug.add(r)
        p.add(ug)
        return p

    @staticmethod
    def _undo_button(label, done_msg, fn, ctx):
        b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        b.add_css_class("pill")

        def clicked(_b):
            b.set_sensitive(False)

            def done(_res):
                b.set_label("Done")
                ctx.toast(done_msg, ok=True)

            def failed(e):
                b.set_sensitive(True)
                ctx.toast(f"Could not undo: {B.message(e)}")
            B.run_async(fn, done, failed)
        b.connect("clicked", clicked)
        return b


# ---------------------------------------------------------------- about

LOGOS = [Path("/usr/share/arclight/logo/eclipse-mark.svg"), REPO / "art/eclipse/logo/eclipse-mark.svg",
         Path("/usr/share/arclight/logo/arclight-mark.svg"), REPO / "desktop/logo/arclight-mark.svg"]


class About(Page):
    id, title, icon = "about", "About", "help-about-symbolic"
    keywords = "version about hostname kernel cpu memory gpu"

    def load(self):
        return B.call("sys.info")

    def build(self, i, ctx):
        p = prefs_page()
        g = group()
        # The photo, frosted, behind the mark: a blurred crop around the golden sun (apps/glass.py asset).
        from .. import glass
        hero_file = glass.asset("hero.jpg")
        ov = Gtk.Overlay()
        ov.add_css_class("arc-about-hero")
        if hero_file:
            pic = Gtk.Picture.new_for_filename(str(hero_file))
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_can_shrink(True)
            pic.set_size_request(-1, 230)
            ov.set_child(pic)
            shade = Gtk.Box()
            shade.add_css_class("arc-about-glass")
            ov.add_overlay(shade)
        else:
            ov.set_child(Gtk.Box(height_request=230))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.START, valign=Gtk.Align.END,
                      margin_start=26, margin_bottom=20)
        # no logo here: the photo's own eclipse is in the crop, and two suns side by side compete
        brand = Gtk.Label(label=i.get("name") or identity.os_name(), xalign=0)
        brand.add_css_class("arc-brand")
        box.append(brand)
        line = Gtk.Box(width_request=260, halign=Gtk.Align.START)
        line.add_css_class("arc-corona-line")
        box.append(line)
        from arclight.edition import has_ai
        tag = Gtk.Label(label=f"{'AI-native Arch Linux' if has_ai() else 'Arch Linux, ready for Claude Code'}"
                              f" · version {__version__}", xalign=0)
        tag.add_css_class("arc-tagline")
        box.append(tag)
        ov.add_overlay(box)
        g.add(ov)
        p.add(g)
        d = group("This computer")
        d.add(info_row("Computer name", i.get("hostname", "?")))
        d.add(info_row("System", i.get("os") or i.get("name") or "?"))
        d.add(info_row("Kernel", i.get("kernel", "?"), mono=True))
        cpu = i.get("cpu") or {}
        d.add(info_row("Processor", f"{cpu.get('model', '?')} ({cpu.get('threads', '?')} threads)"))
        mem = i.get("memory") or {}
        d.add(info_row("Memory", human(mem.get("total"))))
        for gpu in i.get("gpu") or []:
            d.add(info_row("Graphics", gpu_name(gpu)))
        d.add(info_row("Firmware", (i.get("firmware") or "?").upper()))
        p.add(d)
        # the first-boot intro (apps/intro.py), on demand
        ig = group()
        irow = Adw.ActionRow(title="The intro", subtitle="The short tour from your very first start.")
        irow.add_css_class("arc-row")
        ib = Gtk.Button(label="Play the intro again", valign=Gtk.Align.CENTER)
        ib.add_css_class("pill")
        ib.connect("clicked", lambda _b: subprocess.Popen(["arclight-intro", "--replay"], start_new_session=True))
        irow.add_suffix(ib)
        ig.add(irow)
        p.add(ig)
        return p


def _core_ai_page():
    """The core edition (no built-in AI) shows this page as "Claude Code": helpers, history, undo."""
    from arclight.edition import has_ai
    page = AI()
    if not has_ai():
        page.title, page.icon = "Claude Code", "utilities-terminal-symbolic"
    return page


PAGES = [Appearance(), Wallpaper(), Displays(), Input(), Sound(), Network(), Power(), Keybinds(), Apps(), System(),
         _core_ai_page(), About()]
