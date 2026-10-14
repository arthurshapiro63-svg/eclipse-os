"""Eclipse AI's approval card: no pre-selected "yes", and a yes right after AI-driven input is refused.
Settings: turning on passwordless admin needs a confirmation first."""
from unittest import mock

from _gtk import Adw, Gtk, find_button, settle, shot, texts, wait
from arclight.apps.eclipse_ai import style as ea_style, tools, ui as ea
from arclight.apps.settings import rows
from gi.repository import Gio

app = Adw.Application(application_id="dev.eclipse.tests.Approval", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
try:
    ea_style.install()
except Exception:
    pass

# ---- approval card
answers = []
ap = tools.Approval("Run as root", "pacman -S htop", ["runs as root", "your password is asked next (system prompt)"],
                    root=True)
card = ea.ApprovalCard(ap, lambda c: answers.append(c.approval.approved))
win = Gtk.Window(application=app, title="card")
win.set_default_size(720, 300)
win.set_child(card)
win.present()
settle(1.0)
no, yes = card.buttons
assert not yes.has_focus(), "yes must not be pre-selected"
assert win.get_focus() is not yes

with mock.patch.object(ea, "ai_input_recent", return_value=True):
    yes.emit("clicked")
settle(0.3)
assert answers == [], answers
assert card.guard.get_visible() and "does not count" in card.guard.get_text(), card.guard.get_text()
shot(win, "approval-refused.png")

with mock.patch.object(ea, "ai_input_recent", return_value=False):
    yes.emit("clicked")
settle(0.3)
assert answers == [True], answers
print("card ok")

# ---- settings: passwordless admin asks for a confirmation before anything is applied
applied = []


class Ctx:
    def apply(self, key, value, revert, ok):
        applied.append((key, value))

    def toast(self, *a, **k):
        pass


s = {"key": "system.sudo_nopasswd", "type": "bool", "value": False, "scope": "system", "writable": True,
     "description": "Passwordless admin (unsafe)"}
row = rows.make_row(s, Ctx())
assert "Passwordless admin" in row.get_title(), row.get_title()
assert "Unsafe" in row.get_subtitle(), row.get_subtitle()
w2 = Adw.ApplicationWindow(application=app)
grp = Adw.PreferencesGroup(); grp.add(row)
page = Adw.PreferencesPage(); page.add(grp)
w2.set_content(page); w2.set_default_size(900, 500); w2.present()
settle(0.8)
row.set_active(True)
settle(0.8)
dlg = w2.get_visible_dialog()
assert dlg is not None, "no confirmation dialog"
assert applied == [], applied
assert dlg.get_default_response() == "cancel"
shot(w2, "nopasswd-confirm.png")
dlg.close()   # the close response is "cancel"
settle(0.5)
assert applied == [] and not row.get_active(), (applied, row.get_active())
row.set_active(True)
settle(0.8)
d2 = w2.get_visible_dialog(); d2.emit("response", "on"); d2.force_close()
settle(0.5)
assert applied == [("system.sudo_nopasswd", True)], applied
print("settings ok")
print("PASS")
