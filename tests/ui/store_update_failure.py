"""Store: an update whose AUR part fails shows what failed + Retry, never 'Everything is up to date'."""
import sys

from _gtk import Adw, Gtk, find_button, settle, shot, texts, wait
from arclight.apps.store import app as S, style
from gi.repository import Gio

app = Adw.Application(application_id="dev.eclipse.tests.Store", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
style.install()
win = S.Window(app, lambda w: w.show_section("updates"))
win.set_default_size(1280, 860)
win.present()

wait(lambda: win.state.get("updates") == "ready")
t = texts(win.upd_box)
assert "7 updates ready" in t, t
shot(win, "store-1-updates.png")

win.start_job("update")
wait(lambda: win.state.get("job") in ("partial", "failed", "finished"), 60)
assert win.state["job"] == "partial", win.state
assert win.update_problem["failed"] == ["zen-browser-bin"], win.update_problem
wait(lambda: any(x.startswith("Not updated: ") for x in texts(win.upd_box)) and win.state.get("updates") == "ready")
t = texts(win.upd_box)
assert "Everything is up to date" not in t, t
assert "Some updates did not install" in t, t
assert any(x.startswith("Not updated: zen-browser-bin") for x in t), t
assert any(x.startswith("Updated: ") and "firefox" in x for x in t), t
assert "1 update ready" in t, t                  # the failed AUR update is still listed
assert any("Failure while downloading" in x for x in t) or win.update_problem["diagnostics"], t
assert not any("Everything is up to date" in m for _, m in win.errors)
shot(win, "store-2-partial-failure.png")

retry = find_button(win.upd_box, "Retry")
assert retry is not None, "no Retry button"
retry.emit("clicked")
wait(lambda: win.state.get("job") == "finished", 60)
wait(lambda: win.state.get("updates") == "ready" and "Everything is up to date" in texts(win.upd_box))
assert win.update_problem is None
assert find_button(win.upd_box, "Retry") is None
shot(win, "store-3-after-retry.png")
settle(0.3)
print("PASS")
sys.exit(0)
