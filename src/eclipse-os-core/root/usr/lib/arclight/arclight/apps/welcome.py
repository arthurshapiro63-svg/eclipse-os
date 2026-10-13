"""arclight-welcome: the window shown once on the first login of a new install.

Big, plain buttons for the things that matter on day one: ask the AI, talk to it, settings, bring the files
back from the Google Drive backup, and a health check. Run `arclight-welcome` to see it again.
"""
import os
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
STATE = HOME / ".local/state/arclight/welcome-shown"

CSS = """
/* Liquid glass over the photo (apps/glass.py): a frosted crop of the golden eclipse as the header,
   night glass below, cards as lighter glass tiles; the main card wears the corona. */
window.welcome {
  background-color: rgba($base_rgb, 0.56);
  background-image: MATERIAL;
  color: $text;
  BACKDROP
}
.hero { border-radius: 0; }
.kicker { font-size: $fs_micro; font-weight: 700; letter-spacing: 3px; color: $gold_soft; }
.title { font-size: $fs_display; font-weight: 800; color: #FFFFFF; }
.sub { font-size: $fs_body; color: rgba($text_rgb, 0.78); }
.corona-line {
  min-height: 1px; margin: 6px 0 2px 0;
  background-image: linear-gradient(to right, rgba($gold_rgb, 0.0), rgba($gold_rgb, 0.9) 30%, rgba($gold_soft_rgb, 0.0));
}
button.card {
  background-color: rgba($raised_rgb, 0.40);
  background-image: linear-gradient(to bottom, rgba($text_rgb, 0.05), rgba($text_rgb, 0) 50px);
  border: none; border-radius: $r_lg;
  padding: 14px 16px; color: $text;
  box-shadow: RIM, 0 6px 18px rgba($shadow_rgb, 0.35);
}
button.card:hover {
  background-color: rgba($hover_rgb, 0.55);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.22), inset 0 0 0 1px rgba($gold_rgb, 0.45), 0 0 16px rgba($gold_rgb, 0.18),
              0 6px 18px rgba($shadow_rgb, 0.35);
}
button.card.main {
  background-color: rgba($accent_dim_rgb, 0.62);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.20), transparent 60%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.26), CORONA, 0 6px 18px rgba($shadow_rgb, 0.35);
}
button.card.main .cardtitle { color: $gold_soft; }
.cardtitle { font-size: $fs_lead; font-weight: 700; }
/* keys are the only monospace text; a plain "where/when" line uses the UI font */
.cardkeys { font-size: $fs_small; color: $gold; font-family: "JetBrainsMono Nerd Font", monospace; }
.cardtag { font-size: $fs_small; font-weight: 600; color: $gold_soft; }
.carddesc { font-size: $fs_small; color: rgba($text_rgb, 0.72); }
.foot { font-size: $fs_small; color: $text_dim; }
button.close {
  background-color: rgba($text_rgb, 0.07); color: $text; border: none; border-radius: 999px; padding: 4px 18px;
  box-shadow: inset 0 1px rgba(255,255,255,0.14), inset 0 0 0 1px rgba($text_rgb, 0.08);
}
/* closing Welcome is not destructive: it lights up like every other glass button, never red */
button.close:hover { background-color: rgba($text_rgb, 0.13); box-shadow: inset 0 1px rgba(255,255,255,0.2), inset 0 0 0 1px rgba($gold_rgb, 0.45); }
"""

RESTORE_PROMPT = ("Bring my home folder back from the Google Drive backup (folder 'Arclight home backup'). "
                  "Follow 'Restore from the Google Drive backup' in ~/Projects/arclight/docs/MIGRATION.md or "
                  "`arclight-backup --help`: sign me in to Drive if needed (click it for me), restore, then show "
                  "me the verify result. Secrets come from the old system with `arclight-backup secrets`.")


def os_name():
    from arclight import identity
    return identity.os_name()


def files_missing():
    """True when the home looks fresh (no migrated projects), so restoring is the first thing to offer."""
    p = HOME / "Projects"
    try:
        return not p.is_dir() or sum(1 for _ in p.iterdir()) < 3
    except OSError:
        return True


def run(*cmd):
    subprocess.Popen(list(cmd), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def actions():
    from arclight.aigate import ai_enabled
    ai = ai_enabled()
    acts = []
    if Path("/run/archiso").exists():
        acts.append(("Install it", "On this PC", "Goes next to your current Arch. Your old system stays as it is.",
                     lambda: run("arclight-installer-gui"), True))
    elif files_missing():
        if ai:
            acts.append(("Bring my files back", "From Google Drive", "The AI restores your backup and checks every file.",
                         lambda: run("arclight-ask", "--prefill", RESTORE_PROMPT), True))
        else:
            acts.append(("Bring my files back", "From Google Drive", "Restores your backup and checks every file.",
                         lambda: run("ghostty", "--title=Bring my files back", "-e", "sh", "-c",
                                     "arclight-backup restore --into \"$HOME\"; read -p 'Press Enter to close' _"),
                         True))
    if ai:
        acts.append(("Ask the AI", "Super+Shift+A", "Change, fix, install, open or play anything.",
                     lambda: run("arclight-ask"), not acts))
        if shutil.which("hush") or (HOME / ".local/bin/hush").exists():
            acts.append(("Just talk", "Super+Shift+V", "Same, by voice. Local, nothing leaves the PC.",
                         lambda: run("arclight-ask", "--voice"), False))
    else:
        from arclight.edition import has_ai
        acts.append(("Eclipse Store", "Apps", "Find and install apps. A restore point is made first.",
                     lambda: run("arclight-store"), not acts))
        if not has_ai() and shutil.which("claude"):
            acts.append(("Claude Code", "Super+A", "It can see and run this whole PC for you. Type what you want.",
                         lambda: run("ghostty", "--title=Claude Code", "-e", "claude"), False))
    acts.append(("Settings", "Super+I", "Look, screens, wallpaper, the AI and more." if ai else
                 "Look, screens, wallpaper, apps and more.",
                 lambda: run("arclight-settings"), False))
    acts.append(("Health check", "Takes a minute", "Checks the whole system and says how to fix anything.",
                 lambda: run("ghostty", f"--title={os_name()} health check", "-e", "sh", "-c",
                             "arc doctor; echo; read -p 'Press Enter to close' _"), False))
    return acts


def window_main(argv=None):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    app = Gtk.Application(application_id="dev.arclight.Welcome")

    def activate(app):
        from arclight.apps import glass
        glass.install(CSS.replace("MATERIAL", glass.MATERIAL).replace("BACKDROP", glass.BACKDROP)
                      .replace("CORONA", glass.CORONA).replace("RIM", glass.RIM))
        win = Gtk.ApplicationWindow(application=app, title=f"Welcome to {os_name()}")
        win.add_css_class("welcome")
        win.set_default_size(780, -1)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # header: the photo's golden eclipse, frosted, with the title over the dark sky on its left
        head = Gtk.Overlay()
        hero = glass.asset("hero-lake.png") or glass.asset("hero.jpg")
        if hero:
            pic = Gtk.Picture.new_for_filename(str(hero))
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_can_shrink(True)
            pic.set_size_request(-1, 214)
            pic.add_css_class("hero")
            head.set_child(pic)
        else:
            head.set_child(Gtk.Box(height_request=150))
        htxt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.END,
                       margin_start=32, margin_end=32, margin_bottom=16)
        from arclight.edition import has_ai
        ai = has_ai()
        k = Gtk.Label(label="AI-NATIVE ARCH LINUX" if ai else "ARCH LINUX, READY FOR CLAUDE CODE", xalign=0)
        k.add_css_class("kicker")
        t = Gtk.Label(label=f"Welcome to {os_name()}", xalign=0)
        t.add_css_class("title")
        line = Gtk.Box(width_request=300, halign=Gtk.Align.START)
        line.add_css_class("corona-line")
        s = Gtk.Label(label="Your desktop, your keys, your apps. " + ("The AI can now run the whole machine for you."
                      if ai else "Claude Code can run the whole machine for you."),
                      xalign=0, wrap=True)
        s.add_css_class("sub")
        for w in (k, t, line, s):
            htxt.append(w)
        from arclight.apps import motion
        head.add_overlay(motion.SunGlow(strength=0.14))   # the sun's light drifts slowly over the photo
        head.add_overlay(htxt)
        page.append(head)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=22,
                        margin_start=32, margin_end=32)
        page.append(outer)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin_top=18, column_homogeneous=True)
        for i, (title, keys, desc, fn, main) in enumerate(actions()):
            b = Gtk.Button()
            b.add_css_class("card")
            if main:
                b.add_css_class("main")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            keycls = "cardkeys" if keys.startswith(("Super", "Ctrl", "Alt")) else "cardtag"
            for text, cls in ((title, "cardtitle"), (keys, keycls), (desc, "carddesc")):
                lab = Gtk.Label(label=text, xalign=0, wrap=True)
                lab.add_css_class(cls)
                box.append(lab)
            b.set_child(box)

            def clicked(_b, fn=fn):
                fn()
                win.close()
            b.connect("clicked", clicked)
            grid.attach(b, i % 2, i // 2, 1, 1)
        outer.append(grid)
        foot = Gtk.Box(spacing=8, margin_top=16)
        hint = Gtk.Label(label="Open this again any time: search for Welcome in the app launcher.", xalign=0,
                         hexpand=True, wrap=True)
        hint.add_css_class("foot")
        close = Gtk.Button(label="Close")
        close.add_css_class("close")
        close.connect("clicked", lambda _b: win.close())
        foot.append(hint)
        foot.append(close)
        outer.append(foot)
        win.set_child(page)
        # the title, then the cards one by one, then the footer rise in as the window blooms open
        motion.rise([k, t, line, s] + motion.children(grid) + [foot])
        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", lambda _c, kv, *_: (win.close(), True)[1] if kv == Gdk.KEY_Escape else False)
        win.add_controller(kc)
        win.present()

    app.connect("activate", activate)
    return app.run([])


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="arclight-welcome")
    p.add_argument("--once", action="store_true", help="only if never shown before (first login)")
    a = p.parse_args(argv)
    if a.once:
        if STATE.exists():
            return 0
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text("1\n")
    return window_main()
