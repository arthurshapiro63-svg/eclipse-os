"""Arclight Settings: every setting on the machine in one glass window.

It is a thin client of the same settings registry the AI uses (arc set / MCP), so a change
made here, by an agent, or with `arc set` shows up everywhere and persists.

  arclight-settings [--page appearance|wallpaper|displays|input|sound|network|power|keybinds|apps|system|ai|about]
"""
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ... import identity  # noqa: E402
from .. import motion  # noqa: E402
from . import backend as B  # noqa: E402
from . import style  # noqa: E402
from .pages import PAGES  # noqa: E402
from .rows import make_row  # noqa: E402

APP_ID = "dev.arclight.Settings"


class Window(Adw.ApplicationWindow):
    def __init__(self, app, start_page=None):
        super().__init__(application=app, title=f"{identity.short_name()} Settings", default_width=1180, default_height=760)
        self.add_css_class("arclight-settings")
        self.set_icon_name("arclight")
        self.pages = {p.id: p for p in PAGES}
        self.state = {}        # page id -> loading | ready | error
        self.errors = []       # every error shown to the user (tests read this)
        self.rows = {}         # setting key -> row widget (latest built)
        self.containers = {}   # page id -> Gtk.Stack holding spinner / content / error
        self.current = None
        self._search_src = 0
        self._search_gen = 0
        self.update_button = None

        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView(min_sidebar_width=230, max_sidebar_width=280, sidebar_width_fraction=0.22)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)

        # ---- sidebar
        side_tv = Adw.ToolbarView()
        hb = Adw.HeaderBar(show_title=True)
        tbox = Gtk.Box(spacing=8)
        from .pages import LOGOS
        logo_file = next((str(l) for l in LOGOS if l.exists()), None)
        theme = Gtk.IconTheme.get_for_display(self.get_display())
        if theme.has_icon("arclight") or not logo_file:
            logo = Gtk.Image.new_from_icon_name("arclight")
        else:
            logo = Gtk.Image.new_from_file(logo_file)
        logo.set_pixel_size(20)
        tbox.append(logo)
        tl = Gtk.Label(label=f"{identity.short_name()} Settings")
        tl.add_css_class("arc-sidebar-title")
        tbox.append(tl)
        hb.set_title_widget(tbox)
        side_tv.add_top_bar(hb)
        sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.search = Gtk.SearchEntry(placeholder_text="Search every setting")
        self.search.add_css_class("arc-search")
        self.search.connect("search-changed", self._on_search)
        self.search.connect("activate", self._on_search_activate)
        sbox.append(self.search)
        self.sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.add_css_class("arc-sidebar-list")
        self.side_rows = {}
        for p in PAGES:
            row = Gtk.ListBoxRow()
            b = Gtk.Box(spacing=12, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
            b.append(Gtk.Image.new_from_icon_name(p.icon))
            b.append(Gtk.Label(label=p.title, xalign=0))
            row.set_child(b)
            row.page_id = p.id
            self.sidebar.append(row)
            self.side_rows[p.id] = row
        self.sidebar.connect("row-selected", self._on_row_selected)
        # the selection highlight glides from row to row (eased, on the frame clock)
        self.glide = motion.SidebarGlide(self.sidebar)
        sw = Gtk.ScrolledWindow(child=self.glide.widget, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sbox.append(sw)
        side_tv.set_content(sbox)
        self.split.set_sidebar(Adw.NavigationPage(title=f"{identity.short_name()} Settings", child=side_tv, tag="sidebar"))

        # ---- content
        self.content_tv = Adw.ToolbarView()
        chb = Adw.HeaderBar()
        self.content_title = Adw.WindowTitle(title="", subtitle="")
        chb.set_title_widget(self.content_title)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh this page")
        refresh.connect("clicked", lambda _b: self.reload(self.current) if self.current else None)
        chb.pack_end(refresh)
        self.content_tv.add_top_bar(chb)
        # pages cross-fade while their groups rise in one after another (motion.stagger)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=220)
        self.content_tv.set_content(self.stack)
        self.content_page = Adw.NavigationPage(title="Settings", child=self.content_tv, tag="content")
        self.split.set_content(self.content_page)

        self.search_holder = Gtk.Stack()
        self.stack.add_named(self.search_holder, "__search")

        self.navigate(start_page if start_page in self.pages else "appearance")

    # ------------------------------------------------------------ navigation
    def _on_row_selected(self, _lb, row):
        if row is None:
            return
        if self.search.get_text():
            self.search.set_text("")
        self._show(row.page_id)

    def navigate(self, page_id):
        row = self.side_rows.get(page_id)
        if row:
            self.sidebar.select_row(row)  # triggers _show
        self.split.set_show_content(True)

    def _show(self, page_id):
        page = self.pages[page_id]
        self.current = page_id
        self.content_title.set_title(page.title)
        self.content_title.set_subtitle("")
        self.content_page.set_title(page.title)
        if page_id not in self.containers:
            holder = Gtk.Stack()
            self.containers[page_id] = holder
            self.stack.add_named(holder, page_id)
            self.reload(page_id)
        elif self.state.get(page_id) == "ready":
            child = self.containers[page_id].get_visible_child()
            if child is not None:
                motion.stagger(child)
        self.stack.set_visible_child_name(page_id)

    def reload(self, page_id):
        page = self.pages[page_id]
        holder = self.containers[page_id]
        self.state[page_id] = "loading"
        spin = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, spacing=10)
        sp = Adw.Spinner()
        sp.set_size_request(32, 32)
        spin.append(sp)
        lab = Gtk.Label(label=f"Loading {page.title.lower()}…")
        lab.add_css_class("dim-label")
        spin.append(lab)
        self._swap(holder, spin)

        def done(data):
            try:
                widget = page.build(data, self)
            except Exception as e:  # a bug in a page must not take the window down
                import traceback
                traceback.print_exc()
                return failed(e)
            self._swap(holder, widget)
            self.state[page_id] = "ready"
            motion.stagger(widget)

        def failed(e):
            self.state[page_id] = "error"
            self.errors.append((page_id, B.message(e)))
            self._swap(holder, self._error_page(e, lambda: self.reload(page_id)))

        B.run_async(page.load, done, failed)

    @staticmethod
    def _swap(holder, widget):
        old = holder.get_first_child()
        holder.add_child(widget)
        holder.set_visible_child(widget)
        while old is not None:
            nxt = old.get_next_sibling()
            if old is not widget:
                holder.remove(old)
            old = nxt

    def _error_page(self, e, retry):
        unavailable = isinstance(e, B.Unavailable)
        sp = Adw.StatusPage(icon_name="network-offline-symbolic" if unavailable else "dialog-warning-symbolic",
                            title="The settings helper isn't running" if unavailable else "Couldn't load this page",
                            description=GLib.markup_escape_text(
                                "It starts by itself when you log in. Wait a moment, then try again."
                                if unavailable else B.message(e)))
        sp.set_tooltip_text(B.message(e))   # the exact reason, for the curious
        btn = Gtk.Button(label="Try again", halign=Gtk.Align.CENTER)
        btn.add_css_class("pill")
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda _b: retry())
        sp.set_child(btn)
        return sp

    # ------------------------------------------------------------ ctx API used by pages
    def row(self, s):
        r = make_row(s, self)
        self.rows[s["key"]] = r
        return r

    def apply(self, key, value, revert=None, ok=None):
        def done(res):
            if ok:
                ok(res)

        def failed(e):
            if revert:
                revert()
            msg = B.message(e)
            self.errors.append((key, msg))
            from .rows import FRIENDLY
            name = FRIENDLY.get(key, (None,))[0]
            self.toast(f"Couldn't change {name.lower() if name else key}: {msg}")
        B.run_async(lambda: B.call("settings.set", key=key, value=value), done, failed)

    def toast(self, msg, ok=False):
        t = Adw.Toast(title=GLib.markup_escape_text(msg[:300]), timeout=3 if ok else 6)
        self.toasts.add_toast(t)

    def start_upgrade(self, btn, spinner):
        btn.set_sensitive(False)
        btn.set_label("Updating…")
        spinner.set_visible(True)

        def done(res):
            spinner.set_visible(False)
            btn.set_label("Up to date")
            self.toast("System updated", ok=True)
            self.reload("system")

        def failed(e):
            spinner.set_visible(False)
            btn.set_sensitive(True)
            btn.set_label("Update now")
            self.errors.append(("pkg.upgrade", B.message(e)))
            self.toast(f"Update failed: {B.message(e)}")
        B.run_async(lambda: B.call("pkg.upgrade"), done, failed)

    # ------------------------------------------------------------ global search
    def _on_search(self, entry):
        if self._search_src:
            GLib.source_remove(self._search_src)
            self._search_src = 0
        text = entry.get_text().strip()
        if not text:
            if self.current:
                self.stack.set_visible_child_name(self.current)
                self.content_title.set_title(self.pages[self.current].title)
                self.content_title.set_subtitle("")
            return
        self._search_src = GLib.timeout_add(250, self._run_search, text)

    def _on_search_activate(self, entry):
        """Enter: jump to the page owning the first result, if it is a page key."""
        text = entry.get_text().strip().lower()
        for p in PAGES:
            if text and (text in p.title.lower() or text in p.keywords):
                entry.set_text("")
                self.navigate(p.id)
                return

    def _run_search(self, text):
        self._search_src = 0
        self._search_gen += 1
        gen = self._search_gen
        self.sidebar.unselect_all()
        self.content_title.set_title("Search")
        self.content_title.set_subtitle(text)
        self.stack.set_visible_child_name("__search")

        def done(results):
            if gen != self._search_gen:
                return
            page = Adw.PreferencesPage()
            jump = [p for p in PAGES if any(w in (p.title.lower() + " " + p.keywords) for w in text.lower().split())]
            if jump:
                g = Adw.PreferencesGroup(title="Pages")
                for p in jump[:4]:
                    r = Adw.ActionRow(title=p.title, activatable=True)
                    r.add_prefix(Gtk.Image.new_from_icon_name(p.icon))
                    r.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                    r.connect("activated", lambda _r, pid=p.id: (self.search.set_text(""), self.navigate(pid)))
                    g.add(r)
                page.add(g)
            g = Adw.PreferencesGroup(title=GLib.markup_escape_text(f"Settings matching “{text}”"),
                                     description=f"{len(results)} found" if results else "No setting matches. Try other words.")
            for s in results[:40]:
                g.add(self.row(s))
            page.add(g)
            self._swap(self.search_holder, page)
            self.state["__search"] = "ready"

        def failed(e):
            if gen != self._search_gen:
                return
            self.errors.append(("search", B.message(e)))
            self._swap(self.search_holder, self._error_page(e, lambda: self._run_search(text)))
        self.state["__search"] = "loading"
        B.run_async(lambda: B.call("settings.search", text=text), done, failed)
        return False


class SettingsApp(Adw.Application):
    def __init__(self, start_page=None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.start_page = start_page
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        style.install()

    def do_activate(self):
        if self.window is None:
            self.window = Window(self, self.start_page)
        self.window.present()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    page = search = None
    if "--search" in argv:
        i = argv.index("--search")
        search = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    if "--page" in argv:
        i = argv.index("--page")
        page = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    if "--fake" in argv:
        argv.remove("--fake")
        os.environ["ARCLIGHT_SETTINGS_FAKE"] = "1"
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    app = SettingsApp(page)
    if search:
        app.connect("activate", lambda a: GLib.timeout_add(600, lambda: a.window.search.set_text(search) or False))
    return app.run(argv[:1])
