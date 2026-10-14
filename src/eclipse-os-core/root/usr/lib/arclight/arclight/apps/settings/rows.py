"""One generic row factory: turns a setting description from the registry into the right widget.

    bool                      -> switch
    int/float with min..max   -> slider with a live value label (debounced)
    int/float without range   -> spin button
    enum                      -> drop-down
    string/path/gradient/...  -> entry with an apply button
    read-only                 -> plain row showing the value
Every change is sent at once through ctx.apply(); on failure the widget snaps back and a toast
shows the daemon's message.
"""
from gi.repository import Adw, GLib, Gtk


# Plain words for the settings whose registry description is written for the AI / power users.
# key -> (title, hint shown under it or None, extras). extras: "pct" shows 0..1 as a percent;
# "options" turns a number-coded setting into a drop-down of words.
FRIENDLY = {
    "appearance.opacity_active": ("Focused window", "How solid the window you use is", {"pct": True}),
    "appearance.opacity_inactive": ("Other windows", "How see-through the rest are", {"pct": True}),
    "appearance.blur": ("Frosted glass", "Blur what is behind windows", {}),
    "appearance.blur_size": ("Frost amount", None, {}),
    "appearance.blur_passes": ("Frost smoothness", "Higher looks smoother but uses more graphics power", {}),
    "appearance.blur_vibrancy": ("Glass colour", "How much colour shows through the glass", {"pct": True}),
    "appearance.dim_inactive": ("Dim other windows", None, {}),
    "appearance.dim_strength": ("Dim amount", None, {"pct": True}),
    "appearance.gaps_in": ("Space between windows", None, {}),
    "appearance.gaps_out": ("Space at the screen edge", None, {}),
    "appearance.border_size": ("Window border", None, {}),
    "appearance.rounding": ("Rounded corners", None, {}),
    "appearance.active_border": ("Focused border colour", "A colour, or two colours and an angle", {}),
    "appearance.glow": ("Glow around the focused window", None, {}),
    "appearance.moving_light": ("Moving light", "A slow light circles the focused window. Off: always still", {}),
    "appearance.shadow": ("Window shadows", None, {}),
    "appearance.animations": ("Animations", None, {}),
    "appearance.layout": ("How windows tile", None,
                          {"labels": {"dwindle": "Split in halves", "master": "One big, the rest stacked",
                                      "scrolling": "Side by side, scrolling"}}),
    "shell.current": ("Desktop shell", "The bar, dock and launcher",
                      {"labels": {"dms": "DankMaterialShell", "arthur": "Eclipse Quickshell"}}),
    "audio.volume": ("Volume", None, {}),
    "audio.muted": ("Mute speakers", None, {}),
    "audio.mic_volume": ("Microphone volume", None, {}),
    "audio.mic_muted": ("Mute microphone", None, {}),
    "audio.output": ("Play sound on", None, {}),
    "network.networking": ("Networking", "Turns all network connections on or off", {}),
    "network.wifi": ("Wi-Fi", None, {}),
    "bluetooth.enabled": ("Bluetooth", None, {}),
    "display.brightness": ("Brightness", None, {}),
    "display.tearing": ("Allow tearing in games", "Less input lag, small visual tears", {}),
    "display.vrr": ("Adaptive sync", "Smoother games on screens that support it",
                    {"options": [(0, "Off"), (1, "On"), (2, "Only in full screen")]}),
    "cursor.hide_after": ("Hide the mouse pointer after", "Seconds without moving. 0 = never", {}),
    "idle.lock_after": ("Lock the screen after", "Seconds without use. 0 = never", {}),
    "idle.screen_off_after": ("Turn the screen off after", "Seconds without use. 0 = never", {}),
    "input.keyboard_layout": ("Keyboard layout", "For example us, gb, de or fr", {}),
    "input.keyboard_options": ("Keyboard options", "For example caps:escape", {}),
    "input.repeat_rate": ("Key repeat speed", "Letters per second when held", {}),
    "input.repeat_delay": ("Key repeat delay", "Wait before a held key repeats (ms)", {}),
    "input.mouse_speed": ("Mouse speed", "Left is slower, right is faster", {}),
    "input.mouse_accel": ("Mouse acceleration", "flat, adaptive, or empty for the default", {}),
    "input.natural_scroll": ("Natural scrolling", "Content follows your fingers on the touchpad", {}),
    "input.follow_mouse": ("Focus follows the mouse", None,
                           {"options": [(0, "Off: click to focus"), (1, "Always"), (2, "On click only"),
                                        (3, "Keyboard stays, mouse moves")]}),
    "power.profile": ("Power mode", None,
                      {"labels": {"power-saver": "Save battery", "balanced": "Balanced", "performance": "Fastest"}}),
    "system.hostname": ("Computer name", "How this PC shows on your network", {}),
    "system.timezone": ("Time zone", "Region/City, for example Europe/London", {}),
    "system.ntp": ("Set the time automatically", None, {}),
    "system.locale": ("Language and region", "For example en_US.UTF-8", {}),
    "system.swappiness": ("Swap use", "Higher uses the disk sooner. Normal:\u00a060", {}),
    "system.auto_snapshot": ("Restore point before updates", "Only on whole-disk installs", {}),
    "system.sudo_nopasswd": ("Passwordless admin", "Unsafe. Off: sudo, apps and the AI ask for your password before "
                             "changing the system. On: any program running as you can change the whole system", {
                                 "confirm_on": ("Turn off the password for admin?",
                                                "Programs that run as you, AI agents included, could then install "
                                                "software, change system files and become root without asking you. "
                                                "Only do this if you trust everything you run. The system asks for "
                                                "your password one last time to turn it on.")}),
    "ai.enabled": ("Use the AI features", "Ask, Eclipse AI, Fix with AI and routines. Off: no AI anywhere", {}),
    "appearance.eclipse_look": ("Eclipse look", "The eclipse theme, wallpaper and boot animation. "
                                "Off: plain graphite, same features", {}),
    "ai.agent": ("Which AI does the work", "Used by Ask and by Fix with AI",
                 {"labels": {"claude": "Claude", "codex": "Codex"}}),
    "ai.ask_model": ("Model", "Leave empty for the AI's own default", {}),
    "ai.voice": ("Speak button in Ask", "Talk instead of typing. Stays on this PC", {}),
    "ai.autofix": ("Fix broken services on its own", "Off: the AI asks you first", {}),
    "ai.notify_failures": ("Tell me when a service breaks", "With a Fix with AI button", {}),
    "ai.indicator": ("Show a banner while the AI uses the mouse", None, {}),
    "ai.auto_game_mode": ("Totality in games", "Totality turns on by itself in games", {}),
    "wallpaper.living": ("Follow the time of day", "Night, dawn, midday and dusk", {}),
    "wallpaper.living_sunrise": ("Sunrise", "When the day starts, like 06:30", {}),
    "wallpaper.living_sunset": ("Sunset", "When the evening starts, like 19:00", {}),
    "wallpaper.folder": ("Wallpaper folder", "Super+W cycles through the pictures in it", {}),
}


def friendly(s):
    """(title, hint, extras) for a setting: the plain words above, else its own description."""
    f = FRIENDLY.get(s.get("key"))
    if s.get("arc_title"):     # a page can word one row for its context
        return (s["arc_title"], f[1] if f else None, f[2] if f else {})
    if f:
        return f
    if s["key"].startswith("display.") and s["key"].endswith(".scale"):
        return ("Scale", "1 = 100%, 1.5 = 150%", {})
    if s["key"].startswith("display.") and s["key"].endswith(".mode"):
        return ("Resolution and refresh rate", None, {})
    return (title_of(s), None, {})


def title_of(s):
    d = (s.get("description") or s["key"]).strip()
    first = d.split(" ", 1)[0]
    if not d or "." in first or "_" in first:  # keep identifiers like vm.swappiness as written
        return d or s["key"]
    return d[0].upper() + d[1:]


def fmt(v, s):
    if v is None:
        return "—"
    if s.get("pct") and isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{round(v * 100)}%"
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, float):
        txt = f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:.0f}"
    else:
        txt = str(v)
    unit = s.get("unit")
    return f"{txt} {unit}" if unit and unit not in ("%",) else (f"{txt}%" if unit == "%" else txt)


class Guard:
    """Suppress change signals while the code (not the user) is setting a widget's value."""

    def __init__(self):
        self.on = False

    def __enter__(self):
        self.on = True

    def __exit__(self, *a):
        self.on = False


def _decorate(row, s):
    row.add_css_class("arc-row")
    # the setting's name for the AI and `arc set` lives in the tooltip, not under every row
    row.set_tooltip_text((f"{s['description']}\n" if s.get("description") else "") + f"Name for the AI: {s['key']}")
    if s.get("scope") == "system":
        icon = Gtk.Image.new_from_icon_name("system-lock-screen-symbolic")
        icon.set_tooltip_text("Changes the whole system. Asks for your password")
        icon.add_css_class("dim-label")
        row.add_suffix(icon)
    return row


def make_row(s, ctx):
    """s: one entry of settings.list/get/search. ctx: object with .apply(key, value, revert) and .toast(msg)."""
    t, key, value = s.get("type"), s["key"], s.get("value")
    title, hint, extra = friendly(s)
    title, hint = GLib.markup_escape_text(title), GLib.markup_escape_text(hint or "")
    if extra.get("pct"):
        s = dict(s, pct=True)
    if s.get("error") and value is None:
        row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(f"Not available here: {s['error'][:80]}"))
        row.set_sensitive(False)
        return _decorate(row, s)
    if not s.get("writable", True):
        row = Adw.ActionRow(title=title, subtitle=hint)
        lab = Gtk.Label(label=fmt(value, s), ellipsize=3, max_width_chars=40, selectable=True)
        lab.add_css_class("dim-label")
        row.add_suffix(lab)
        return _decorate(row, s)

    guard = Guard()

    if t == "bool":
        row = Adw.SwitchRow(title=title, subtitle=hint)
        row.set_active(bool(value))
        state = {"v": bool(value)}

        def on_active(r, _p):
            if guard.on:
                return
            new = r.get_active()

            def revert():
                with guard:
                    r.set_active(state["v"])

            def ok(_res):
                state["v"] = new
            if new and extra.get("confirm_on"):
                heading, body = extra["confirm_on"]
                dlg = Adw.AlertDialog(heading=heading, body=body)
                dlg.add_response("cancel", "Keep the password")
                dlg.add_response("on", "Turn it off anyway")
                dlg.set_response_appearance("on", Adw.ResponseAppearance.DESTRUCTIVE)
                dlg.set_default_response("cancel")
                dlg.set_close_response("cancel")
                dlg.connect("response", lambda _d, resp: ctx.apply(key, new, revert, ok) if resp == "on" else revert())
                dlg.present(row.get_root())
                return
            ctx.apply(key, new, revert, ok)
        row.connect("notify::active", on_active)
        return _decorate(row, s)

    if extra.get("options") and t in ("int", "enum"):
        opts = extra["options"]
        labels = [w for _v, w in opts]
        vals = [v for v, _w in opts]
        row = Adw.ComboRow(title=title, subtitle=hint)
        cur = value
        try:
            cur = int(value)
        except (TypeError, ValueError):
            pass
        if cur not in vals:
            vals.append(cur)
            labels.append(str(cur))
        row.set_model(Gtk.StringList.new(labels))
        row.set_selected(vals.index(cur))
        state = {"i": row.get_selected()}

        def on_opt(r, _p):
            if guard.on:
                return
            i = r.get_selected()
            if i == Gtk.INVALID_LIST_POSITION:
                return

            def revert():
                with guard:
                    r.set_selected(state["i"])

            def ok(_res):
                state["i"] = i
            ctx.apply(key, vals[i], revert, ok)
        row.connect("notify::selected", on_opt)
        return _decorate(row, s)

    if t == "enum" and s.get("choices"):
        choices = [str(c) for c in s["choices"]]
        words = extra.get("labels") or {}
        row = Adw.ComboRow(title=title, subtitle=hint)
        cur = str(value) if value is not None else None
        if cur is not None and cur not in choices:
            choices.append(cur)
        row.set_model(Gtk.StringList.new([words.get(c, c) for c in choices]))
        if cur in choices:
            row.set_selected(choices.index(cur))
        state = {"i": row.get_selected()}

        def on_sel(r, _p):
            if guard.on:
                return
            i = r.get_selected()
            if i == Gtk.INVALID_LIST_POSITION:
                return

            def revert():
                with guard:
                    r.set_selected(state["i"])

            def ok(_res):
                state["i"] = i
            ctx.apply(key, choices[i], revert, ok)
        row.connect("notify::selected", on_sel)
        return _decorate(row, s)

    if t in ("int", "float"):
        is_int = t == "int"
        lo, hi = s.get("min"), s.get("max")
        cur = value if isinstance(value, (int, float)) else 0
        if lo is not None and hi is not None and (not is_int or hi - lo <= 400):
            row = Adw.ActionRow(title=title, subtitle=hint)
            step = 1 if is_int else max(0.01, round((hi - lo) / 100, 3))
            adj = Gtk.Adjustment(value=cur, lower=lo, upper=hi, step_increment=step, page_increment=step * 10)
            scale = Gtk.Scale(adjustment=adj, draw_value=False, hexpand=False, valign=Gtk.Align.CENTER)
            scale.set_digits(0 if is_int else 2)
            scale.set_size_request(200, -1)
            scale.add_css_class("arc-scale")
            lab = Gtk.Label(label=fmt(cur, s), width_chars=6, xalign=1)
            lab.add_css_class("numeric")
            lab.add_css_class("arc-value")
            box = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
            box.append(scale)
            box.append(lab)
            row.add_suffix(box)
            state = {"v": cur, "src": 0}

            def fire():
                state["src"] = 0
                v = int(round(adj.get_value())) if is_int else round(adj.get_value(), 3)
                if v == state["v"]:
                    return False

                def revert():
                    with guard:
                        adj.set_value(state["v"])
                        lab.set_label(fmt(state["v"], s))

                def ok(_res):
                    state["v"] = v
                ctx.apply(key, v, revert, ok)
                return False

            def on_changed(a):
                v = int(round(a.get_value())) if is_int else round(a.get_value(), 3)
                lab.set_label(fmt(v, s))
                if guard.on:
                    return
                if state["src"]:
                    GLib.source_remove(state["src"])
                state["src"] = GLib.timeout_add(260, fire)
            adj.connect("value-changed", on_changed)
            row.arc_adjustment = adj
            return _decorate(row, s)
        # no range: spin row
        lo = -1e9 if lo is None else lo
        hi = 1e9 if hi is None else hi
        row = Adw.SpinRow.new_with_range(lo, hi, 1 if is_int else 0.01)
        row.set_title(title)
        row.set_subtitle(hint)
        row.set_digits(0 if is_int else 3)
        row.set_value(cur)
        state = {"v": cur}

        def on_spin(r, _p):
            if guard.on:
                return
            v = int(r.get_value()) if is_int else r.get_value()

            def revert():
                with guard:
                    r.set_value(state["v"])

            def ok(_res):
                state["v"] = v
            ctx.apply(key, v, revert, ok)
        row.connect("notify::value", on_spin)
        return _decorate(row, s)

    # strings, paths, gradients, colours, gaps, raw: an entry that applies on Enter / the check button
    row = Adw.EntryRow(title=title)
    row.set_text("" if value is None else str(value))
    row.set_show_apply_button(True)
    state = {"v": row.get_text()}

    def on_apply(r):
        new = r.get_text()

        def revert():
            r.set_text(state["v"])

        def ok(_res):
            state["v"] = new
        ctx.apply(key, new, revert, ok)
    row.connect("apply", on_apply)
    return _decorate(row, s)
