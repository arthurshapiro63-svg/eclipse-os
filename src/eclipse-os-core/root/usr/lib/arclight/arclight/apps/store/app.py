"""Eclipse Store: find, install, open, remove and update apps, in plain words.

Official Arch packages, the AUR and (when flatpak is installed) Flathub in one list. Installs go through
arclightd (the system asks for the administrator password) and a restore point is made first (btrfs installs).

  arclight-store                    the store
  arclight-store --demo             fake data and fake installs (nothing is touched, no root, no network)
  arclight-store --search TEXT      open with a search
  arclight-store --app NAME         open one app's page
  arclight-store --page installed|updates
"""
import os
import re
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from ... import identity  # noqa: E402
from .. import glass  # noqa: E402
from .. import motion  # noqa: E402
from . import backend as B  # noqa: E402
from . import catalog  # noqa: E402
from . import style  # noqa: E402

APP_ID = "dev.arclight.Store"
LOGOS = [Path("/usr/share/arclight/logo/eclipse-logo-64.png"), glass.REPO / "art/eclipse/logo/icons/eclipse-logo-64.png",
         Path("/usr/share/arclight/logo/eclipse-mark.svg"), glass.REPO / "art/eclipse/logo/eclipse-mark.svg"]


# ------------------------------------------------------------------ small widget helpers
def lab(text, cls=None, xalign=0.0, wrap=True, lines=0, **kw):
    w = Gtk.Label(label=text, xalign=xalign, wrap=wrap, **kw)
    if wrap:
        w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if lines:
        w.set_lines(lines)
        w.set_ellipsize(Pango.EllipsizeMode.END)
    for c in (cls or "").split():
        w.add_css_class(c)
    return w


def box(vertical=True, spacing=0, cls=None, **kw):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing, **kw)
    for c in (cls or "").split():
        b.add_css_class(c)
    return b


def button(text, cls, cb=None, **kw):
    b = Gtk.Button(label=text, **kw)
    for c in cls.split():
        b.add_css_class(c)
    if cb:
        b.connect("clicked", lambda _b: cb())
    return b


def a11y(w, text):
    try:
        w.update_property([Gtk.AccessibleProperty.LABEL], [text])
    except Exception:
        pass


def badge(source):
    b = lab(catalog.SOURCES.get(source, {}).get("badge", source).upper(), f"st-badge {source}", wrap=False)
    b.set_valign(Gtk.Align.CENTER)
    return b


def installed_badge():
    b = lab("INSTALLED", "st-badge installed", wrap=False)
    b.set_valign(Gtk.Align.CENTER)
    return b


def clamp(child, width=1040):
    c = Adw.Clamp(maximum_size=width, tightening_threshold=width - 80)
    c.set_child(child)
    return c


def scrolled(child):
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    sw.set_child(child)
    return sw


_BASE_RE = re.compile(r"-(bin|git|appimage|desktop|nightly|beta|stable|launcher)$")


_PAPIRUS = []


def _papirus(display):
    """Papirus-Dark as a second icon theme (it knows almost every app, installed or not)."""
    if not _PAPIRUS:
        t = None
        if Path("/usr/share/icons/Papirus-Dark").is_dir():
            t = Gtk.IconTheme()
            t.set_display(display) if hasattr(t, "set_display") else None
            t.set_theme_name("Papirus-Dark")
        _PAPIRUS.append(t)
    return _PAPIRUS[0]


def resolve_icon(display, item, entry=None):
    """('icon', name) | ('papirus', name) | ('file', path) | None. Menu entry first, then the curated icon,
    then the package name; the active icon theme first, then Papirus."""
    theme = Gtk.IconTheme.get_for_display(display)
    pap = _papirus(display)
    cands = []
    if entry and entry.get("icon"):
        cands.append(entry["icon"])
    if item.get("icon"):
        cands.append(item["icon"])
    n = item.get("name", "")
    cands += [n, _BASE_RE.sub("", n), _BASE_RE.sub("", _BASE_RE.sub("", n))]
    cands = [c for c in cands if c]
    for c in cands:
        if c.startswith("/"):
            if os.path.exists(c):
                return ("file", c)
            continue
        if theme.has_icon(c):
            return ("icon", c)
    for c in cands:
        if pap is not None and not c.startswith("/") and pap.has_icon(c):
            return ("papirus", c)
    f = catalog.appstream_icon(n, flatpak=item.get("source") == "flatpak")
    return ("file", f) if f else None


def icon_widget(display, item, size, entry=None):
    r = resolve_icon(display, item, entry)
    if r:
        if r[0] == "icon":
            img = Gtk.Image.new_from_icon_name(r[1])
        elif r[0] == "papirus":
            img = Gtk.Image.new_from_paintable(_papirus(display).lookup_icon(
                r[1], None, size, 1, Gtk.TextDirection.NONE, 0))
        else:
            img = Gtk.Image.new_from_file(r[1])
        img.set_pixel_size(size)
        img.set_size_request(size, size)
        img.set_valign(Gtk.Align.CENTER)
        img.arc_icon = r
        return img
    title = item.get("title") or catalog.nice_title(item.get("name", "?"))
    letter = (re.sub(r"[^A-Za-z0-9]", "", title)[:1] or "?").upper()
    l = Gtk.Label(label=letter, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    l.add_css_class("st-letter")
    l.set_size_request(size, size)
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_size_new_absolute(int(size * 0.5) * Pango.SCALE))
    l.set_attributes(attrs)
    l.arc_icon = None
    return l


# the source tree first (only exists when run from the repo), then the installed photo
PHOTO = [glass.REPO / "desktop/wallpapers/arclight-eclipse.jpg", Path("/usr/share/arclight/wallpapers/arclight-eclipse.jpg"),
         Path("/usr/share/backgrounds/arclight/arclight-eclipse.jpg")]


def hero_file():
    """The hero: a wide band of Arthur's photo (sky, eclipse, horizon, the car's roof), lightly frosted, made
    once and cached. Falls back to the shipped crops when the photo or PIL is missing."""
    src = next((p for p in PHOTO if p.exists()), None)
    if src:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "arclight"
        out = cache / "store-hero-v1.jpg"
        try:
            if out.exists() and out.stat().st_mtime >= src.stat().st_mtime and \
                    (out.with_suffix(".src").read_text() if out.with_suffix(".src").exists() else "") == str(src):
                return out
            cache.mkdir(parents=True, exist_ok=True)
            try:
                from PIL import Image, ImageEnhance, ImageFilter
                im = Image.open(src).convert("RGB")
                w, h = im.size
                im = im.crop((0, 0, w, int(h * 0.58)))
                im.thumbnail((2200, 2200))
                im = im.filter(ImageFilter.GaussianBlur(1.6))
                im = ImageEnhance.Brightness(im).enhance(0.92)
                im.save(out, quality=90)
            except ImportError:      # no Pillow: same band, unfrosted (the scrim keeps text readable)
                gi.require_version("GdkPixbuf", "2.0")
                from gi.repository import GdkPixbuf
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(src), 2200, -1, True)
                band = pb.new_subpixbuf(0, 0, pb.get_width(), int(pb.get_height() * 0.58))
                band.savev(str(out), "jpeg", ["quality"], ["90"])
            out.with_suffix(".src").write_text(str(src))
            return out
        except Exception:
            pass
    return glass.asset("hero-wide.jpg") or glass.asset("hero.jpg")


def logo_widget(size):
    f = next((str(p) for p in LOGOS if p.exists()), None)
    if f:
        img = Gtk.Image.new_from_file(f)
    else:
        img = Gtk.Image.new_from_icon_name("arclight")
    img.set_pixel_size(size)
    return img


# ------------------------------------------------------------------ the window
class Window(Adw.ApplicationWindow):
    def __init__(self, app, start=None):
        super().__init__(application=app, title=f"{identity.short_name()} Store", default_width=1200, default_height=800)
        self.add_css_class("arclight-settings")      # the shared Settings glass (sidebar, header, lists)
        self.add_css_class("arclight-store")
        self.set_icon_name("arclight")
        self.errors = []            # every error shown to the user (the test reads this)
        self.state = {}             # page -> loading | ready | error
        self.installed = {}         # name -> version
        self.cur = catalog.curated_index()
        self.cats = catalog.curated()
        self.job = None             # the running job (dict) or None
        self.job_views = {}         # app key -> progress view of that page
        self.pages = {}             # tag -> NavigationPage (current instances)
        self.tiles = {}             # name -> home tile button
        self.result_rows = []       # rows in the current search (test hook)
        self.search_gen = 0
        self.search_src = 0
        self.search_state = {}
        self.updates = None
        self.update_problem = None  # the last update that did not finish cleanly (shown until one does)
        self.confirm = None         # the open remove dialog (test hook)
        self.home_dirty = False

        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView(min_sidebar_width=230, max_sidebar_width=270, sidebar_width_fraction=0.21)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)
        self._build_sidebar()
        self.nav = Adw.NavigationView()
        self.nav.connect("popped", self._on_popped)
        self.split.set_content(Adw.NavigationPage(title="Store", child=self.nav, tag="content"))

        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", self._key)
        self.add_controller(kc)

        self.refresh_installed(lambda: self.refresh_home_badges())
        self.load_updates()
        self.show_section("home")
        if start:
            GLib.idle_add(lambda: (start(self), False)[1])

    # -------------------------------------------------------------- chrome
    def _build_sidebar(self):
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar(show_title=True)
        t = box(False, 10)
        t.append(logo_widget(22))
        tl = lab(f"{identity.short_name()} Store", "arc-sidebar-title", wrap=False)
        t.append(tl)
        hb.set_title_widget(t)
        tv.add_top_bar(hb)
        side = box(spacing=0)
        self.sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, margin_top=8)
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.add_css_class("arc-sidebar-list")
        self.side_rows = {}
        for sid, title, icon in (("home", "Home", "go-home-symbolic"), ("installed", "Installed", "view-app-grid-symbolic"),
                                 ("updates", "Updates", "software-update-available-symbolic")):
            row = Gtk.ListBoxRow()
            b = box(False, 12, margin_start=6, margin_end=6, margin_top=5, margin_bottom=5)
            b.append(Gtk.Image.new_from_icon_name(icon))
            b.append(lab(title, wrap=False, hexpand=True))
            if sid == "updates":
                self.update_count = lab("", "st-count", wrap=False, xalign=0.5)
                self.update_count.set_visible(False)
                b.append(self.update_count)
            row.set_child(b)
            row.section = sid
            a11y(row, title)
            self.sidebar.append(row)
            self.side_rows[sid] = row
        self.sidebar.connect("row-activated", lambda _l, r: self.show_section(r.section))
        side.append(self.sidebar)
        side.append(Gtk.Box(vexpand=True))
        ask = Gtk.Button()
        ask.add_css_class("st-askcard")
        ab = box(spacing=2)
        ab.append(lab("Ask the AI", "st-askcard-title"))
        ab.append(lab("It can find, install and fix apps for you.", "st-askcard-sub"))
        ask.set_child(ab)
        a11y(ask, "Ask the AI")
        ask.connect("clicked", lambda _b: self.ask("I need an app that "))
        ask.set_visible(self.ai_on)
        side.append(ask)
        tv.set_content(side)
        self.split.set_sidebar(Adw.NavigationPage(title=f"{identity.short_name()} Store", child=tv, tag="sidebar"))

    def _page(self, tag, title, content, ask_prefill):
        """A content page: glass header with an 'Ask the AI' pill, scrolled content."""
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_title_widget(Adw.WindowTitle(title=title))
        askb = button("Ask the AI", "st-askbtn", lambda: self.ask(ask_prefill() if callable(ask_prefill) else ask_prefill))
        askb.set_tooltip_text("Ask the AI about this")
        askb.set_visible(self.ai_on)
        hb.pack_end(askb)
        tv.add_top_bar(hb)
        tv.set_content(content)
        page = Adw.NavigationPage(title=title, child=tv, tag=tag)
        page.header = hb
        page.ask_button = askb
        return page

    def _key(self, _c, kv, _code, mods):
        if kv == Gdk.KEY_Escape and len(self.nav.get_navigation_stack()) > 1:
            self.nav.pop()
            return True
        if kv in (Gdk.KEY_f, Gdk.KEY_F) and mods & Gdk.ModifierType.CONTROL_MASK:
            self.show_section("home")
            GLib.idle_add(lambda: (self.home_search.grab_focus(), False)[1])
            return True
        return False

    def _on_popped(self, _nav, page):
        tag = page.get_tag() or ""
        self.pages.pop(tag, None)
        if self.home_dirty and self.nav.get_visible_page() is self.pages.get("home"):
            self.refresh_home_badges()

    def toast(self, msg, ok=False):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(msg[:300]), timeout=3 if ok else 6))

    @property
    def ai_on(self):
        """The 'Use the AI' choice (Settings → AI): when it is off the Store hides every Ask button."""
        if getattr(self, "_ai_on", None) is None:
            try:
                from ...aigate import ai_enabled
                self._ai_on = bool(ai_enabled())
            except Exception:
                self._ai_on = True
        return self._ai_on

    def ask(self, prefill):
        if not self.ai_on:
            from ...aigate import off_text
            self.toast(off_text())
            return
        try:
            B.ask(prefill)
            self.toast("Ask is open. Type or say what you need.", ok=True)
        except Exception as e:  # noqa: BLE001
            self.errors.append(("ask", B.message(e)))
            self.toast(f"Could not open Ask: {B.message(e)}")

    # -------------------------------------------------------------- sections
    def show_section(self, sid):
        row = self.side_rows.get(sid)
        if row and self.sidebar.get_selected_row() is not row:
            self.sidebar.select_row(row)
        builder = {"home": self.build_home, "installed": self.build_installed, "updates": self.build_updates}[sid]
        page = builder()
        self.pages = {page.get_tag(): page}
        self.nav.replace([page])
        self.split.set_show_content(True)

    def refresh_installed(self, then=None):
        def done(v):
            self.installed = v
            if then:
                then()
        B.run_async(B.installed, done, lambda e: self.errors.append(("installed", B.message(e))))

    def is_installed(self, item):
        if item.get("source") == "flatpak":
            return item["name"] in self.installed
        return item["name"] in self.installed

    # -------------------------------------------------------------- home
    def build_home(self):
        content = box(spacing=26, margin_top=18, margin_bottom=36, margin_start=28, margin_end=28)
        content.append(self._hero())
        self.tiles = {}
        self.cat_boxes = {}
        for c in self.cats:
            sec = box(spacing=12)
            head = box(spacing=2)
            head.append(lab(c["title"], "st-sec-title"))
            if c.get("sub"):
                head.append(lab(c["sub"], "st-sec-sub"))
            sec.append(head)
            fb = Gtk.FlowBox(homogeneous=True, min_children_per_line=2, max_children_per_line=4, column_spacing=14,
                             row_spacing=14, selection_mode=Gtk.SelectionMode.NONE)
            for a in c["apps"]:
                t = self._tile(a)
                fb.append(t)
            sec.append(fb)
            self.cat_boxes[c["id"]] = sec
            content.append(sec)
        page = self._page("home", "Home", scrolled(clamp(content, 1080)), "I need an app that ")
        # the hero rises first, then the sections; the first rows of tiles follow one by one
        motion.rise(motion.children(content))
        first = [t for c in self.cats[:1] for t in (self.tiles.get(a["name"]) for a in c["apps"]) if t]
        motion.rise([t.get_parent() or t for t in first[:8]], first=2)
        self.state["home"] = "ready"
        self.home_dirty = False
        return page

    def _hero(self):
        ov = Gtk.Overlay()
        ov.add_css_class("st-hero")
        ov.set_overflow(Gtk.Overflow.HIDDEN)
        hero = hero_file()
        if hero:
            pic = Gtk.Picture.new_for_filename(str(hero))
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_can_shrink(True)
            pic.set_size_request(-1, 300)
            ov.set_child(pic)
        else:
            ov.set_child(Gtk.Box(height_request=300))
        scrim = box(cls="st-hero-scrim")
        scrim.set_can_target(False)
        ov.add_overlay(scrim)
        ov.add_overlay(motion.SunGlow())   # the sun's light drifts slowly across the photo (real clock)
        txt = box(spacing=8, valign=Gtk.Align.CENTER, margin_start=40, margin_end=40)
        txt.append(lab(f"{identity.short_name().upper()} STORE", "st-kicker"))
        txt.append(lab("Find your next app", "st-hero-title"))
        line = Gtk.Box(width_request=280, halign=Gtk.Align.START)
        line.add_css_class("st-corona-line")
        txt.append(line)
        txt.append(lab("Games, art, code and AI. One click to install.", "st-hero-sub"))
        self.home_search = Gtk.SearchEntry(placeholder_text="Search apps, like Krita or Steam", margin_top=14,
                                           width_request=520, halign=Gtk.Align.START)
        self.home_search.add_css_class("st-search")
        a11y(self.home_search, "Search apps")
        self.home_search.connect("activate", lambda e: self.open_search(e.get_text()))
        self.home_search.connect("search-changed", lambda e: self._debounce(e.get_text(), home=True))
        txt.append(self.home_search)
        ov.add_overlay(txt)
        return ov

    def _tile(self, a):
        item = dict(a)
        b = Gtk.Button()
        b.add_css_class("st-tile")
        v = box(spacing=8)
        top = box(False, 12)
        top.append(icon_widget(self.get_display(), item, 48))
        right = box(spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        right.append(lab(a.get("title") or catalog.nice_title(a["name"]), "st-tile-name", lines=1, max_width_chars=16))
        badges = box(False, 6)
        badges.append(badge(a["source"]))
        inst = installed_badge()
        inst.set_visible(self.is_installed(a))
        badges.append(inst)
        right.append(badges)
        top.append(right)
        v.append(top)
        v.append(lab(a.get("blurb", ""), "st-tile-blurb", lines=2, max_width_chars=24, width_chars=24))
        b.set_child(v)
        b.inst_badge = inst
        b.item = item
        a11y(b, a.get("title") or a["name"])
        b.connect("clicked", lambda _b: self.open_app(item))
        self.tiles[a["name"]] = b
        return b

    def refresh_home_badges(self):
        for n, t in self.tiles.items():
            t.inst_badge.set_visible(self.is_installed(t.item))
        self.home_dirty = False

    # -------------------------------------------------------------- search
    def _debounce(self, text, home):
        """Search as you type: wait until typing pauses, then search (Enter searches at once)."""
        if self.search_src:
            GLib.source_remove(self.search_src)
            self.search_src = 0
        text = (text or "").strip()
        if len(text) < 2:
            return

        def fire():
            self.search_src = 0
            if home:
                self.open_search(text)
                self.search_entry.grab_focus()
                self.search_entry.set_position(-1)
            elif text != getattr(self, "search_query", None):
                self.run_search(text)
            return False
        self.search_src = GLib.timeout_add(700, fire)

    def open_search(self, text):
        text = (text or "").strip()
        if not text:
            return
        page = self.pages.get("search")
        if page is None:
            page = self._build_search_page()
            self.pages["search"] = page
            self.nav.push(page)
        else:
            self.nav.pop_to_page(page)
        if self.search_entry.get_text() != text:
            self.search_entry.set_text(text)
        if self.search_src:
            GLib.source_remove(self.search_src)
            self.search_src = 0
        self.run_search(text)

    def _build_search_page(self):
        content = box(spacing=16, margin_top=18, margin_bottom=36, margin_start=28, margin_end=28)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search apps")
        self.search_entry.add_css_class("st-search")
        a11y(self.search_entry, "Search apps")
        self.search_entry.connect("activate", lambda e: self.run_search(e.get_text().strip()))
        self.search_entry.connect("search-changed", lambda e: self._debounce(e.get_text(), home=False))
        content.append(self.search_entry)
        st = box(False, 10)
        self.search_spin = Adw.Spinner()
        self.search_spin.set_size_request(18, 18)
        st.append(self.search_spin)
        self.search_status = lab("", "st-status", hexpand=True)
        st.append(self.search_status)
        content.append(st)
        self.search_ask_top = self._ask_row()
        content.append(self.search_ask_top)
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.add_css_class("boxed-list")
        self.results.add_css_class("st-results")
        self.results.connect("row-activated", lambda _l, r: self.open_app(r.item))
        content.append(self.results)
        self.search_note = lab("", "st-note")
        content.append(self.search_note)
        self.search_ask_bottom = self._ask_row()
        content.append(self.search_ask_bottom)
        page = self._page("search", "Search", scrolled(clamp(content, 980)),
                          lambda: f"Find and install the app: {self.search_entry.get_text().strip()}")
        return page

    def _ask_row(self):
        b = Gtk.Button()
        b.add_css_class("st-askrow")
        h = box(False, 14)
        img = Gtk.Image.new_from_icon_name("system-search-symbolic")
        img.set_pixel_size(28)
        img.add_css_class("st-link")
        h.append(img)
        v = box(spacing=2, hexpand=True)
        v.append(lab("Can't find it? Ask the AI to find and install it", "st-askrow-title"))
        v.append(lab("Say what you want in your own words. It looks everywhere for you.", "st-askrow-sub"))
        h.append(v)
        b.set_child(h)
        a11y(b, "Can't find it? Ask the AI to find and install it")
        b.connect("clicked", lambda _b: self.ask(f"Find and install the app: {self.search_entry.get_text().strip()}"))
        b.set_visible(self.ai_on)
        return b

    def run_search(self, text):
        if not text:
            return
        self.search_gen += 1
        gen = self.search_gen
        self.search_query = text
        self.state["search"] = "loading"
        self.search_state = {"repo": "loading", "aur": "loading"}
        if B.has_flatpak():
            self.search_state["flatpak"] = "loading"
        self.search_raw = {}
        self.search_errors = {}
        self.search_spin.set_visible(True)
        self._render_results()
        for src, fn in (("repo", B.search_repo), ("aur", B.search_aur), ("flatpak", B.search_flatpak)):
            if src not in self.search_state:
                continue

            def done(rows, src=src):
                if gen != self.search_gen:
                    return
                self.search_raw[src] = rows or []
                self.search_state[src] = "ready"
                self._render_results()
                if src == "repo":
                    self._load_sizes(gen, [r["name"] for r in rows or []][:60])

            def failed(e, src=src):
                if gen != self.search_gen:
                    return
                self.search_state[src] = "error"
                self.search_errors[src] = B.message(e)
                self.errors.append((f"search.{src}", B.message(e)))
                self._render_results()
            B.run_async(lambda fn=fn: fn(text), done, failed)

    def _load_sizes(self, gen, names):
        def done(sz):
            if gen != self.search_gen:
                return
            self.sizes_cache = getattr(self, "sizes_cache", {})
            self.sizes_cache.update({k: v for k, v in (sz or {}).items() if v})
            for row in self.result_rows:
                if row.item["source"] == "repo" and row.item["name"] in self.sizes_cache:
                    row.size_label.set_label(catalog.human_size(self.sizes_cache[row.item["name"]]))
                    row.size_label.set_visible(True)
        B.run_async(lambda: B.sizes(names), done, lambda e: None)

    def _render_results(self):
        st = self.search_state
        merged = []
        for src in ("repo", "flatpak", "aur"):
            for r in self.search_raw.get(src, []):
                r = dict(r)
                r["installed"] = r.get("installed") or self.is_installed(r)
                merged.append(catalog.decorate(r, self.cur))
        ranked = catalog.rank(merged, self.search_query, self.cur)[:80]
        child = self.results.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.results.remove(child)
            child = nxt
        self.result_rows = []
        sizes = getattr(self, "sizes_cache", {})
        for r in ranked:
            row = self._result_row(r, sizes.get(r["name"]) if r["source"] == "repo" else r.get("size"))
            self.results.append(row)
            self.result_rows.append(row)
        if self.result_rows and not getattr(self, "_results_risen", None) == self.search_query:
            self._results_risen = self.search_query      # once per search, not on every partial update
            motion.rise(self.result_rows[:9])
        loading = [s for s, v in st.items() if v == "loading"]
        names = {"repo": "Arch", "aur": "the AUR", "flatpak": "Flathub"}
        where = ", ".join(names[s] for s in st)
        if loading:
            self.search_status.set_label(f"Looking in {where}…" if not ranked else
                                         f"{len(ranked)} found so far. Still looking in {', '.join(names[s] for s in loading)}…")
        else:
            self.search_status.set_label(f"{len(ranked)} found for “{self.search_query}”" if ranked else
                                         f"Nothing found for “{self.search_query}”. Try other words" + (", or ask the AI." if self.ai_on else "."))
        self.search_spin.set_visible(bool(loading))
        self.results.set_visible(bool(ranked))
        notes = []
        if st.get("aur") == "error":
            notes.append("Community apps (AUR) could not be searched, so some may be missing.")
        if st.get("repo") == "error":
            notes.append("The main app list could not be searched. Check the internet and try again.")
        if st.get("flatpak") == "error":
            notes.append("Flathub could not be searched.")
        self.search_note.set_label(" ".join(notes))
        self.search_note.set_tooltip_text("\n".join(f"{k}: {v}" for k, v in self.search_errors.items()) or None)
        self.search_note.set_visible(bool(notes))
        done = not loading
        self.search_ask_top.set_visible(self.ai_on and done and not ranked)
        self.search_ask_bottom.set_visible(self.ai_on and bool(ranked))
        if done:
            self.state["search"] = "ready" if not (st.get("repo") == "error" and not ranked) else "error"

    def _result_row(self, r, size):
        row = Gtk.ListBoxRow(activatable=True)
        h = box(False, 14)
        h.append(icon_widget(self.get_display(), r, 44))
        mid = box(spacing=3, hexpand=True, valign=Gtk.Align.CENTER)
        top = box(False, 8)
        top.append(lab(r["title"], "st-row-name", wrap=False, ellipsize=Pango.EllipsizeMode.END))
        top.append(badge(r["source"]))
        if r.get("installed"):
            top.append(installed_badge())
        if r.get("out_of_date"):
            top.append(lab("OLD", "st-badge old", wrap=False, valign=Gtk.Align.CENTER))
        top.append(lab(r["name"], "st-pkgname", wrap=False, valign=Gtk.Align.CENTER, lines=1))
        mid.append(top)
        mid.append(lab(r["blurb"], "st-row-blurb", lines=2))
        h.append(mid)
        sz = lab(catalog.human_size(size) if size else ("Built on your PC" if r["source"] == "aur" else ""),
                 "st-size" if r["source"] != "aur" else "st-note", wrap=False, xalign=1.0, valign=Gtk.Align.CENTER)
        sz.set_visible(bool(size) or r["source"] == "aur")
        h.append(sz)
        chev = Gtk.Image.new_from_icon_name("go-next-symbolic")
        chev.add_css_class("st-chev")
        h.append(chev)
        row.set_child(h)
        row.item = r
        row.size_label = sz
        a11y(row, f"{r['title']} ({catalog.SOURCES[r['source']]['badge']})")
        return row

    # -------------------------------------------------------------- app page
    def open_app(self, item, then=None):
        item = dict(item)
        c = self.cur.get(item["name"]) if item.get("source") != "flatpak" else None
        if c:
            for k in ("title", "blurb", "icon"):
                item.setdefault(k, c.get(k))
        catalog.decorate(item, self.cur)
        key = f"app:{item.get('source', 'repo')}:{item['name']}"
        old = self.pages.get(key)
        if old is not None and old in self.nav.get_navigation_stack():
            self.nav.pop_to_page(old)
            if then:
                then(old)
            return old
        page = self._build_app_page(item, key)
        self.pages[key] = page
        self.nav.push(page)
        if then:
            then(page)
        return page

    def _build_app_page(self, item, key):
        installed = self.is_installed(item)
        entry = None
        if installed:
            try:
                entry = B.desktop_entry(item)
            except Exception:
                entry = None
        content = box(spacing=22, margin_top=22, margin_bottom=40, margin_start=32, margin_end=32)
        head = box(False, 22)
        icon_wrap = box(cls="st-icon-tile", valign=Gtk.Align.START)
        big = icon_widget(self.get_display(), item, 96, entry)
        for side in ("start", "end", "top", "bottom"):
            getattr(big, f"set_margin_{side}")(14)
        icon_wrap.append(big)
        head.append(icon_wrap)
        info = box(spacing=8, hexpand=True, valign=Gtk.Align.CENTER)
        info.append(lab(item.get("title") or catalog.nice_title(item["name"]), "st-app-title"))
        info.append(lab(item.get("blurb") or "", "st-app-blurb"))
        bl = box(False, 8, margin_top=2)
        bl.append(badge(item.get("source", "repo")))
        inst_b = installed_badge()
        inst_b.set_visible(installed)
        bl.append(inst_b)
        bl.append(lab(item["name"], "st-pkgname", wrap=False, ellipsize=Pango.EllipsizeMode.END, valign=Gtk.Align.CENTER))
        info.append(bl)
        head.append(info)
        content.append(head)

        # actions
        acts = box(False, 12)
        primary = button("Install", "st-primary")
        remove = button("Remove", "st-danger")
        askb = button("Ask the AI about it", "st-ghost gold")
        askb.set_visible(self.ai_on)
        acts.append(primary)
        term_note = lab(f"No window. Type {item['name']} in a terminal to use it.", "st-snap", wrap=False,
                        valign=Gtk.Align.CENTER)
        term_note.set_visible(False)
        acts.append(term_note)
        acts.append(remove)
        acts.append(Gtk.Box(hexpand=True))
        acts.append(askb)
        content.append(acts)

        # progress
        pv = self._progress_view()
        content.append(pv.root)

        # facts
        facts = box(cls="st-card", spacing=0)
        grid = Gtk.Grid(column_spacing=28, row_spacing=14)
        facts.append(grid)
        content.append(facts)
        about_card = box(cls="st-card", spacing=8)
        about_card.append(lab("About it", "st-fact-key"))
        about = lab(item.get("description") or item.get("blurb") or "", "st-about", selectable=True)
        about_card.append(about)
        content.append(about_card)

        page = self._page(key, item.get("title") or item["name"], scrolled(clamp(content, 980)),
                          f"About the app {item.get('title') or item['name']} ({item['name']}): ")
        motion.rise([w for w in motion.children(content) if w is not pv.root])   # head, buttons, cards come in in turn
        page.item = item
        page.entry = entry
        page.primary, page.remove, page.ask_about = primary, remove, askb
        page.inst_badge = inst_b
        page.term_note = term_note
        page.progress = pv
        page.grid = grid
        page.about = about
        page.details = None
        primary.connect("clicked", lambda _b: self._primary_clicked(page))
        remove.connect("clicked", lambda _b: self.confirm_remove(page))
        askb.connect("clicked", lambda _b: self.ask(f"About the app {item.get('title') or item['name']}: "))
        a11y(primary, "Install")
        self._sync_app_buttons(page)
        self._fill_facts(page, None)
        self.state[key] = "loading"

        def done(d):
            page.details = d
            if d.get("description") and not item.get("description"):
                about.set_label(catalog.plain(d["description"], 400) if len(d["description"]) > 400 else d["description"])
            self._fill_facts(page, d)
            self.state[key] = "ready"

        def failed(e):
            self.state[key] = "ready"          # the page still works without the extra facts
            self.errors.append(("details", B.message(e)))
            self._fill_facts(page, {"error": B.message(e)})
        B.run_async(lambda: B.details(item), done, failed)
        # a job for this app may already be running (opened again from Installed)
        if self.job and self.job.get("key") == key:
            self.job["view"] = pv
        return page

    def _sync_app_buttons(self, page):
        installed = self.is_installed(page.item)
        busy = self.job is not None
        page.inst_badge.set_visible(installed)
        if installed:
            page.primary.set_label("Open")
            a11y(page.primary, "Open")
            can_open = page.item.get("source") == "flatpak" or page.entry is not None or B.fake_mode()
            page.primary.set_sensitive(not busy)
            page.primary.set_visible(can_open)
            page.term_note.set_visible(not can_open)
        else:
            page.primary.set_visible(True)
            page.term_note.set_visible(False)
            page.primary.set_label("Install")
            a11y(page.primary, "Install")
            page.primary.set_sensitive(not busy)
            page.primary.set_tooltip_text(None)
        page.remove.set_visible(installed and not catalog.is_system_part(page.item["name"]))
        page.remove.set_sensitive(not busy)

    def _fill_facts(self, page, d):
        g = page.grid
        while g.get_first_child():
            g.remove(g.get_first_child())
        item = page.item
        src = item.get("source", "repo")
        d = d or {}
        version = self.installed.get(item["name"]) if self.is_installed(item) else None
        version = version or d.get("version") or item.get("version") or "…"
        newer = d.get("repo_version") if d.get("repo_version") and d.get("repo_version") != version else None
        size = d.get("size") or item.get("size")
        rows = [("Version", version + (f"  (new: {newer})" if newer else ""), None),
                ("Size", catalog.human_size(size) if size else ("Built on your PC" if src == "aur" else ("…" if not d else "Not known")),
                 "Space it takes on the disk" if size else None),
                ("Source", catalog.SOURCES[src]["long"], catalog.SOURCES[src]["note"])]
        if src == "aur" and d.get("votes") is not None:
            rows.append(("Votes", f"{d['votes']} people like it" + ("  ·  marked out of date" if d.get("out_of_date") else ""), None))
        if d.get("url"):
            rows.append(("Website", d["url"], None))
        if d.get("error"):
            rows.append(("Note", "Some details could not be loaded.", d["error"][:160]))
        for i, (k, v, note) in enumerate(rows):
            g.attach(lab(k, "st-fact-key", valign=Gtk.Align.START), 0, i, 1, 1)
            vb = box(spacing=2, hexpand=True)
            if k == "Website":
                link = Gtk.Label(xalign=0, wrap=True)
                link.set_markup(f'<a href="{GLib.markup_escape_text(v)}">{GLib.markup_escape_text(v)}</a>')
                link.add_css_class("st-fact-val")
                vb.append(link)
            else:
                vb.append(lab(v, "st-fact-val"))
            if note:
                vb.append(lab(note, "st-fact-note"))
            g.attach(vb, 1, i, 1, 1)

    def _primary_clicked(self, page):
        if self.is_installed(page.item):
            ok = False
            try:
                ok = B.open_app(page.item, page.entry)
            except Exception as e:  # noqa: BLE001
                self.errors.append(("open", B.message(e)))
            self.toast(f"Opening {page.item.get('title')}…" if ok else "It could not be opened.", ok=ok)
            return
        self.start_job("install", page)

    def confirm_remove(self, page):
        item = page.item
        title = item.get("title") or item["name"]
        dlg = Adw.AlertDialog(heading=f"Remove {title}?",
                              body=f"{title} will be taken off this PC. Your own files stay."
                                   + (" A restore point is made first." if item.get("source") != "flatpak" else ""))
        dlg.add_response("keep", "Keep it")
        dlg.add_response("remove", "Yes, remove it")
        dlg.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("keep")
        dlg.set_close_response("keep")

        def resp(_d, r):
            self.confirm = None
            if r == "remove":
                self.start_job("remove", page)
        dlg.connect("response", resp)
        self.confirm = dlg
        dlg.present(self)
        return dlg

    # -------------------------------------------------------------- progress + jobs
    def _progress_view(self):
        pv = type("PV", (), {})()
        root = box(cls="st-card", spacing=10)
        root.set_visible(False)
        top = box(False, 12)
        pv.now = lab("", "st-prog-now", hexpand=True)
        top.append(pv.now)
        pv.pct = lab("", "st-prog-pct", wrap=False)
        top.append(pv.pct)
        root.append(top)
        pv.bar = Gtk.ProgressBar()
        pv.bar.add_css_class("st-bar")
        pv.ease = motion.EasedProgress(pv.bar)   # the bar glides to each new value (real clock)
        root.append(pv.bar)
        pv.line = lab("", "st-prog-line", lines=1)
        root.append(pv.line)
        pv.result = lab("", "st-done")
        pv.result.set_visible(False)
        root.append(pv.result)
        pv.snap = lab("", "st-snap")
        pv.snap.set_visible(False)
        root.append(pv.snap)
        pv.exp = Gtk.Expander(label="Show what it is doing")
        pv.buf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=pv.buf, editable=False, cursor_visible=False, monospace=True,
                          wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=10, right_margin=10)
        tv.add_css_class("st-log")
        sw = Gtk.ScrolledWindow(min_content_height=180, max_content_height=260, propagate_natural_height=True)
        sw.set_child(tv)
        sw.add_css_class("st-logbox")
        pv.sw = sw
        pv.exp.set_child(sw)
        root.append(pv.exp)
        pv.root = root
        pv.lines = 0
        return pv

    def start_job(self, action, page=None):
        if self.job is not None:
            self.toast("Wait a moment: something else is being installed or updated.")
            return False
        item = page.item if page is not None else None
        pv = page.progress if page is not None else self.upd_progress
        title = (item.get("title") or item["name"]) if item else "everything"
        prog = catalog.Progress({"install": "install", "remove": "remove", "update": "update"}[action], title)
        job = {"action": action, "item": item, "page": page, "view": pv, "progress": prog, "lines": [],
               "key": page.get_tag() if page is not None else "updates", "pulse": 0, "done": False}
        self.job = job
        pv.ease.jump(0.0)
        if not pv.root.get_visible():
            motion.rise([pv.root])
        pv.root.set_visible(True)
        pv.result.set_visible(False)
        pv.snap.set_visible(False)
        pv.line.set_label("")
        pv.line.set_visible(True)
        pv.buf.set_text("")
        pv.lines = 0
        pv.result.remove_css_class("st-err")
        pv.result.add_css_class("st-done")
        pv.bar.remove_css_class("st-bar-failed")
        verb = {"install": "Installing", "remove": "Removing", "update": "Updating"}[action]
        self._show_progress(job, f"{verb} {title}" if item else "Updating everything")
        if page is not None:
            self._sync_app_buttons(page)
        if action == "update":
            self.upd_button.set_sensitive(False)
        self.state["job"] = "running"
        job["pulse"] = GLib.timeout_add(110, self._pulse, job)

        def on_line(line):
            job["lines"].append(line)
            GLib.idle_add(self._job_line, job, line)

        B.run_async(lambda: B.run_job(action, item, on_line), lambda r: self._job_done(job, r),
                    lambda e: self._job_failed(job, e))
        return True

    def _pulse(self, job):
        if job["done"]:
            return False
        if job["progress"].pulsing:
            job["view"].bar.pulse()
        return True

    def _show_progress(self, job, text=None):
        pv, p = job["view"], job["progress"]
        pv.now.set_label(text or p.text)
        if p.pulsing:
            pv.pct.set_label("")
        else:
            pv.ease.set(p.fraction)
            pv.pct.set_label(f"{int(p.fraction * 100)}%")

    def _job_line(self, job, line):
        pv = job["view"]
        if job["progress"].feed(line):
            self._show_progress(job)
        pv.line.set_label(line.strip()[:160])
        end = pv.buf.get_end_iter()
        pv.buf.insert(end, ("\n" if pv.lines else "") + line)
        pv.lines += 1
        if pv.exp.get_expanded():
            adj = pv.sw.get_vadjustment()
            GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])
        return False

    def _finish_job(self, job):
        job["done"] = True
        self.job = None
        self.state["job"] = "idle"
        if job["pulse"]:
            GLib.source_remove(job["pulse"])
            job["pulse"] = 0

    def _job_done(self, job, res):
        r = (res or {}).get("result")
        if job["action"] == "update" and isinstance(r, dict) and r.get("status") in ("partial", "failed"):
            return self._update_incomplete(job, res)
        self._finish_job(job)
        pv, item, action = job["view"], job["item"], job["action"]
        if action == "update":
            self.update_problem = None          # a clean run clears the last failure
        pv.ease.set(1.0)
        pv.pct.set_label("100%")
        title = (item.get("title") or item["name"]) if item else None
        msg = {"install": f"{title} is installed.", "remove": f"{title} was removed.",
               "update": "Everything is up to date."}[action]
        pv.now.set_label({"install": "Installed", "remove": "Removed", "update": "Updated"}[action])
        pv.line.set_visible(False)   # the last raw pacman line is noise once it is done (the log keeps it)
        pv.result.set_label(msg)
        pv.result.set_visible(True)
        snap = (res or {}).get("snapshot")
        if snap:
            pv.snap.set_label("A restore point was made first. If anything breaks, you can go back to it.")
            pv.snap.set_visible(True)
            pv.snap.arc_snapshot = snap
        job["result"] = res
        self.toast(msg, ok=True)
        self.home_dirty = True

        def after():
            page = job["page"]
            if page is not None:
                if action == "install":
                    try:
                        page.entry = B.desktop_entry(page.item)
                    except Exception:
                        page.entry = None
                    if page.entry or page.item.get("source") == "flatpak" or B.fake_mode():
                        pv.result.set_label(msg + " Press Open to start it.")
                self._sync_app_buttons(page)
                self._fill_facts(page, page.details)
            self.refresh_home_badges()
            if action == "update":
                self.load_updates(rebuild=True)
            self.state["job"] = "finished"
        self.refresh_installed(after)

    def _job_failed(self, job, e):
        self._finish_job(job)
        pv = job["view"]
        raw = B.message(e)
        if isinstance(e, B.JobError) and e.output:
            raw = e.output
        plain = catalog.plain_error(raw)
        item = job.get("item")
        title = (item.get("title") or item["name"]) if item else None
        pv.now.set_label({"install": f"Couldn't install {title}", "remove": f"Couldn't remove {title}",
                          "update": "Couldn't update"}.get(job["action"], "It did not work"))
        pv.pct.set_label("")
        pv.bar.add_css_class("st-bar-failed")   # the bar stops and goes red: it is not still working
        pv.line.set_visible(False)              # the plain reason below says it; the open log has the rest
        pv.result.set_label(plain)
        pv.result.remove_css_class("st-done")
        pv.result.add_css_class("st-err")
        pv.result.set_visible(True)
        if raw and raw not in pv.buf.get_text(pv.buf.get_start_iter(), pv.buf.get_end_iter(), False):
            pv.buf.insert(pv.buf.get_end_iter(), ("\n" if pv.lines else "") + raw)
        pv.exp.set_expanded(True)
        self.errors.append((f"job.{job['action']}", raw))
        self.toast(plain)
        if job["page"] is not None:
            self._sync_app_buttons(job["page"])
        if job["action"] == "update":
            self.upd_button.set_sensitive(True)
        self.state["job"] = "failed"

    def _update_incomplete(self, job, res):
        """An update that finished with failures: say exactly what was and was not updated, keep the
        diagnostics, and offer Retry. Never reported as "up to date"."""
        self._finish_job(job)
        r = res["result"]
        pv = job["view"]
        done, failed = r.get("updated") or [], r.get("failed") or []
        partial = r.get("status") == "partial"
        pv.now.set_label("Some updates did not install" if partial else "The updates did not install")
        pv.pct.set_label("")
        pv.bar.add_css_class("st-bar-failed")
        pv.line.set_visible(False)
        msg = (f"Updated {len(done)} package{'s' if len(done) != 1 else ''}. " if done else "") + \
              f"Not updated: {', '.join(failed)}."
        pv.result.set_label(msg)
        pv.result.remove_css_class("st-done")
        pv.result.add_css_class("st-err")
        pv.result.set_visible(True)
        diag = r.get("diagnostics") or ""
        if diag and diag not in pv.buf.get_text(pv.buf.get_start_iter(), pv.buf.get_end_iter(), False):
            pv.buf.insert(pv.buf.get_end_iter(), ("\n" if pv.lines else "") + diag)
        pv.exp.set_expanded(True)
        snap = res.get("snapshot")
        if snap:
            pv.snap.set_label("A restore point was made first. If anything breaks, you can go back to it.")
            pv.snap.set_visible(True)
            pv.snap.arc_snapshot = snap
        self.update_problem = {"status": r.get("status"), "updated": done, "failed": failed, "diagnostics": diag}
        self.errors.append(("job.update", msg + ("\n" + diag if diag else "")))
        self.toast(msg)
        self.upd_button.set_sensitive(True)
        self.home_dirty = True
        self.state["job"] = "partial" if partial else "failed"
        self.refresh_installed(lambda: (self.refresh_home_badges(), self.load_updates(rebuild=True)))

    def _problem_card(self):
        """The last update's failure, until an update finishes cleanly: what failed, why, and Retry."""
        pb = self.update_problem
        card = box(cls="st-card red", spacing=8)
        card.append(lab("The last update did not finish" if pb["status"] == "failed"
                        else "Some updates did not install", "st-empty-title"))
        if pb["updated"]:
            card.append(lab(f"Updated: {', '.join(pb['updated'][:12])}"
                            + (f" and {len(pb['updated']) - 12} more" if len(pb["updated"]) > 12 else ""), "st-about"))
        card.append(lab(f"Not updated: {', '.join(pb['failed'])}", "st-about"))
        if pb["diagnostics"]:
            card.append(lab(catalog.plain_error(pb["diagnostics"]), "st-note"))
            exp = Gtk.Expander(label="Details")
            exp.set_child(lab(pb["diagnostics"][-3000:], "st-note", selectable=True))
            card.append(exp)
        row = box(False, 10)
        retry = button("Retry", "st-primary", lambda: self.start_job("update"))
        a11y(retry, "Retry the update")
        row.append(retry)
        card.append(row)
        return card

    # -------------------------------------------------------------- updates
    def load_updates(self, rebuild=False):
        def done(ups):
            self.updates = ups or []
            n = len(self.updates)
            self.update_count.set_label(str(n))
            self.update_count.set_visible(n > 0)
            if rebuild or (self.pages.get("updates") and self.state.get("updates") == "loading"):
                self._fill_updates()

        def failed(e):
            self.updates = None
            self.upd_error = B.message(e)
            self.errors.append(("updates", self.upd_error))
            if self.pages.get("updates"):
                self._fill_updates()
        B.run_async(B.updates, done, failed)

    def build_updates(self):
        self.upd_box = box(spacing=18, margin_top=22, margin_bottom=40, margin_start=32, margin_end=32)
        page = self._page("updates", "Updates", scrolled(clamp(self.upd_box, 980)),
                          "Check my system updates and tell me if anything needs care: ")
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Check again")
        a11y(refresh, "Check again")
        refresh.connect("clicked", lambda _b: (self._updates_loading(), self.load_updates(rebuild=True)))
        page.header.pack_end(refresh)
        self.upd_progress = self._progress_view()
        self.pages["updates"] = page
        if self.updates is None:
            self._updates_loading()
            self.load_updates(rebuild=True)
        else:
            self._fill_updates()
        return page

    def _clear(self, b):
        c = b.get_first_child()
        while c is not None:
            n = c.get_next_sibling()
            b.remove(c)
            c = n

    def _updates_loading(self):
        self.state["updates"] = "loading"
        self._clear(self.upd_box)
        sp = box(spacing=12, halign=Gtk.Align.CENTER, margin_top=80)
        s = Adw.Spinner()
        s.set_size_request(36, 36)
        sp.append(s)
        sp.append(lab("Checking for updates…", "st-status", xalign=0.5))
        self.upd_box.append(sp)

    def _fill_updates(self):
        b = self.upd_box
        self._clear(b)
        ups = self.updates
        self.upd_button = button("Update all", "st-primary", lambda: self.start_job("update"))
        a11y(self.upd_button, "Update all")
        if ups is None:
            card = box(cls="st-card red", spacing=6)
            card.append(lab("Could not check for updates", "st-empty-title"))
            card.append(lab(catalog.plain_error(getattr(self, "upd_error", "")), "st-about"))
            card.append(lab(getattr(self, "upd_error", ""), "st-note", selectable=True))
            b.append(card)
            self.state["updates"] = "error"
            return
        problems = [u for u in ups if "error" in u]      # e.g. the AUR could not be checked
        ups = [u for u in ups if "name" in u]
        if getattr(self, "update_problem", None):
            b.append(self._problem_card())
        head = box(False, 18, cls="st-card")
        if ups:
            t = box(spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
            t.append(lab(f"{len(ups)} update{'s' if len(ups) != 1 else ''} ready", "st-big-num"))
            t.append(lab("Newer versions with fixes. A restore point is made first.", "st-sec-sub"))
            head.append(t)
            self.upd_button.set_valign(Gtk.Align.CENTER)
            head.append(self.upd_button)
        elif problems or getattr(self, "update_problem", None):
            t = box(spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
            t.append(lab("No other updates found", "st-big-num"))
            t.append(lab("; ".join(p["error"] for p in problems) or "Retry the update above when you are ready.",
                         "st-sec-sub"))
            head.append(t)
        else:
            mark = lab("✓", "st-ok-mark", xalign=0.5, valign=Gtk.Align.CENTER, wrap=False)
            head.append(mark)
            t = box(spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
            t.append(lab("Everything is up to date", "st-big-num"))
            t.append(lab("Nothing to do. Check again any time with the button at the top.", "st-sec-sub"))
            head.append(t)
        b.append(head)
        if problems and ups:
            b.append(lab("; ".join(p["error"] for p in problems), "st-note"))
        b.append(self.upd_progress.root)
        if ups:
            lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            lb.add_css_class("boxed-list")
            lb.add_css_class("st-results")
            for u in ups:
                row = Gtk.ListBoxRow(activatable=False)
                h = box(False, 14)
                item = {"name": u["name"], "source": u.get("source", "repo")}
                catalog.decorate(item, self.cur)
                h.append(icon_widget(self.get_display(), item, 36))
                mid = box(spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
                mid.append(lab(item["title"], "st-row-name", wrap=False, ellipsize=Pango.EllipsizeMode.END))
                if u["name"].lower() != str(item["title"]).lower():  # the package name only when it says more
                    mid.append(lab(u["name"], "st-pkgname", wrap=False, ellipsize=Pango.EllipsizeMode.END))
                h.append(mid)
                vers = box(False, 8, valign=Gtk.Align.CENTER)
                vers.append(lab(u.get("version", ""), "st-ver", wrap=False))
                vers.append(lab("→", "st-ver", wrap=False))
                vers.append(lab(u.get("new_version", ""), "st-ver-new", wrap=False))
                h.append(vers)
                row.set_child(h)
                lb.append(row)
            b.append(lb)
        self.state["updates"] = "ready"

    # -------------------------------------------------------------- installed
    def build_installed(self):
        self.inst_box = box(spacing=16, margin_top=22, margin_bottom=40, margin_start=32, margin_end=32)
        page = self._page("installed", "Installed", scrolled(clamp(self.inst_box, 980)),
                          "About the apps I have installed: ")
        self.state["installed"] = "loading"
        sp = box(spacing=12, halign=Gtk.Align.CENTER, margin_top=80)
        s = Adw.Spinner()
        s.set_size_request(36, 36)
        sp.append(s)
        sp.append(lab("Looking at your apps…", "st-status", xalign=0.5))
        self.inst_box.append(sp)
        self.installed_rows = {}

        def done(apps):
            self._clear(self.inst_box)
            apps = sorted(apps or [], key=lambda a: (a.get("title") or a["name"]).lower())
            head = box(spacing=4)
            head.append(lab(f"{len(apps)} apps you installed", "st-sec-title"))
            head.append(lab("Apps you picked yourself, with a window to open. System parts are not shown.", "st-sec-sub"))
            self.inst_box.append(head)
            lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            lb.add_css_class("boxed-list")
            lb.add_css_class("st-results")
            for a in apps:
                lb.append(self._installed_row(a))
            lb.connect("row-activated", lambda _l, r: self.open_app(r.item))
            self.inst_box.append(lb)
            self.state["installed"] = "ready"

        def failed(e):
            self._clear(self.inst_box)
            self.errors.append(("installed", B.message(e)))
            card = box(cls="st-card red", spacing=6)
            card.append(lab("Could not list your apps", "st-empty-title"))
            card.append(lab(B.message(e), "st-note", selectable=True))
            self.inst_box.append(card)
            self.state["installed"] = "error"
        B.run_async(B.installed_apps, done, failed)
        return page

    def _installed_row(self, a):
        row = Gtk.ListBoxRow(activatable=True)
        item = dict(a)
        c = self.cur.get(item["name"]) if item.get("source") != "flatpak" else None
        if c:
            item["blurb"] = c.get("blurb")
        else:
            item["blurb"] = (catalog.plain(item.get("description")) if item.get("description")
                             else (f"Version {item['version']}" if item.get("version") else ""))
        h = box(False, 14)
        entry = {"icon": a.get("icon")} if a.get("icon") else None
        h.append(icon_widget(self.get_display(), item, 40, entry))
        mid = box(spacing=3, hexpand=True, valign=Gtk.Align.CENTER)
        top = box(False, 8)
        top.append(lab(item.get("title") or item["name"], "st-row-name", wrap=False, ellipsize=Pango.EllipsizeMode.END))
        top.append(badge(item.get("source", "repo")))
        mid.append(top)
        mid.append(lab(item["blurb"] or "", "st-row-blurb", lines=1))
        h.append(mid)
        ob = button("Open", "st-ghost st-small", valign=Gtk.Align.CENTER)
        a11y(ob, f"Open {item.get('title') or item['name']}")
        ob.connect("clicked", lambda _b: self._open_installed(item))
        rb = button("Remove", "st-danger st-small", valign=Gtk.Align.CENTER)
        a11y(rb, f"Remove {item.get('title') or item['name']}")
        rb.connect("clicked", lambda _b: self.open_app(item, then=lambda p: self.confirm_remove(p)))
        h.append(ob)
        h.append(rb)
        rb.set_visible(not catalog.is_system_part(item["name"]))
        row.set_child(h)
        row.item = item
        row.open_button, row.remove_button = ob, rb
        self.installed_rows[item["name"]] = row
        return row

    def _open_installed(self, item):
        ok = False
        try:
            ok = B.open_app(item, catalog.read_desktop(item["desktop"]) if item.get("desktop") and not B.fake_mode() else None)
        except Exception as e:  # noqa: BLE001
            self.errors.append(("open", B.message(e)))
        self.toast(f"Opening {item.get('title') or item['name']}…" if ok else "It could not be opened.", ok=ok)


class StoreApp(Adw.Application):
    def __init__(self, start=None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.start = start
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        style.install()

    def do_activate(self):
        if self.window is None:
            self.window = Window(self, self.start)
        self.window.present()


def main(argv=None):
    import argparse
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="arclight-store", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="fake data and fake installs: nothing is touched")
    ap.add_argument("--search", help="open with this search")
    ap.add_argument("--app", help="open this package's page")
    ap.add_argument("--page", choices=["home", "installed", "updates"])
    a = ap.parse_args(argv)
    if a.demo:
        os.environ["ARCLIGHT_STORE_FAKE"] = "1"

    def start(win):
        if a.page and a.page != "home":
            win.show_section(a.page)
        if a.search:
            win.open_search(a.search)
        if a.app:
            src = (win.cur.get(a.app) or {}).get("source", "repo")
            win.open_app({"name": a.app, "source": src})
    app = StoreApp(start if (a.search or a.app or a.page) else None)
    return app.run([sys.argv[0] if sys.argv else "arclight-store"])
