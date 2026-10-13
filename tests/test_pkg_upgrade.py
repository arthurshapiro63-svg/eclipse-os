"""Bug 0.1.1-4: a failed AUR update must never come back looking like success."""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _paths  # noqa: F401
from arclight.system import pkg
from arclight.rpc import RPCError

HERE = Path(__file__).resolve().parent


class Sim:
    """pacman/yay as seen by pkg.upgrade: versions before/after, exit codes."""

    def __init__(self, repo_before, repo_after, aur_before, aur_after, aur_pending, repo_code=0, yay_code=0,
                 pending_error=None):
        self.repo, self.repo_after = dict(repo_before), repo_after
        self.aur, self.aur_after = dict(aur_before), aur_after
        self.pending, self.pending_error = aur_pending, pending_error
        self.repo_code, self.yay_code = repo_code, yay_code

    def run(self, cmd, **kw):
        if cmd[:2] == ["pacman", "-Q"]:
            return "".join(f"{n} {v}\n" for n, v in {**self.repo, **self.aur}.items())
        if cmd[:2] == ["pacman", "-Qm"]:
            return "".join(f"{n} {v}\n" for n, v in self.aur.items())
        raise AssertionError(cmd)

    def stream(self, cmd, **kw):
        if cmd[:2] == ["pacman", "-Syu"]:
            if self.repo_code == 0:
                self.repo.update(self.repo_after)
            return {"code": self.repo_code, "stdout": ":: Starting full system upgrade...\n", "stderr": ""}
        if "yay" in cmd:
            self.aur.update(self.aur_after)
            out = "==> ERROR: Failure while downloading source\n" if self.yay_code else "done\n"
            return {"code": self.yay_code, "stdout": out, "stderr": ""}
        raise AssertionError(cmd)

    def aur_pending(self, user):
        if self.pending_error:
            raise RPCError(self.pending_error)
        return [{"name": n, "version": self.aur[n], "new_version": "x"} for n in self.pending]

    def upgrade(self, aur=True):
        with mock.patch.object(pkg, "_check_lock", lambda: None), mock.patch.object(pkg, "run", self.run), \
                mock.patch.object(pkg, "_stream", self.stream), mock.patch.object(pkg, "_aur_pending", self.aur_pending), \
                mock.patch.object(pkg, "which", lambda n: "/usr/bin/yay"), \
                mock.patch.object(pkg, "_user_of", lambda peer: "arthur"), \
                mock.patch.object(pkg.pwd, "getpwnam", lambda u: SimpleNamespace(pw_dir="/home/arthur")):
            return pkg.upgrade(aur=aur)


class Upgrade(unittest.TestCase):
    def test_aur_failure_after_repo_success_is_partial(self):
        r = Sim({"firefox": "1", "mesa": "1"}, {"firefox": "2"}, {"zen-browser-bin": "1", "yay-bin": "1"},
                {"yay-bin": "2"}, ["zen-browser-bin", "yay-bin"], yay_code=1).upgrade()
        self.assertEqual(r["status"], "partial")
        self.assertFalse(r["ok"])
        self.assertEqual(r["failed"], ["zen-browser-bin"])
        self.assertEqual(sorted(r["updated"]), ["firefox", "yay-bin"])
        self.assertIn("Failure while downloading", r["diagnostics"])
        self.assertEqual(r["retry"], {"method": "pkg.upgrade", "params": {"aur": True}})

    def test_aur_failure_with_nothing_else_is_failed(self):
        r = Sim({"firefox": "1"}, {}, {"zen-browser-bin": "1"}, {}, ["zen-browser-bin"], yay_code=1).upgrade()
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["updated"], [])

    def test_yay_error_with_unknown_names_is_still_a_failure(self):
        r = Sim({"a": "1"}, {"a": "2"}, {"x": "1"}, {}, [], yay_code=1, pending_error="AUR unreachable").upgrade()
        self.assertEqual(r["status"], "partial")
        self.assertEqual(len(r["failed"]), 1)
        self.assertIn("yay", r["failed"][0])

    def test_yay_exit_zero_but_package_unchanged_is_a_failure(self):
        r = Sim({}, {}, {"zen-browser-bin": "1"}, {}, ["zen-browser-bin"], yay_code=0).upgrade()
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["failed"], ["zen-browser-bin"])

    def test_everything_ok(self):
        r = Sim({"a": "1"}, {"a": "2"}, {"x": "1"}, {"x": "2"}, ["x"]).upgrade()
        self.assertEqual((r["status"], r["ok"], r["failed"]), ("ok", True, []))
        self.assertEqual(sorted(r["updated"]), ["a", "x"])
        self.assertNotIn("retry", r)

    def test_repo_failure_raises(self):
        with self.assertRaises(RPCError):
            Sim({"a": "1"}, {}, {}, {}, [], repo_code=1).upgrade()

    def test_repo_only_does_not_touch_aur(self):
        r = Sim({"a": "1"}, {"a": "2"}, {"x": "1"}, {}, ["x"], yay_code=1).upgrade(aur=False)
        self.assertEqual(r["status"], "ok")
        self.assertNotIn("aur", r)


class UpdatesList(unittest.TestCase):
    def test_aur_check_failure_is_reported_not_hidden(self):
        with mock.patch.object(pkg, "run_full", lambda *a, **k: {"code": 2, "stdout": "", "stderr": ""}), \
                mock.patch.object(pkg, "which", lambda n: "/usr/bin/yay"), \
                mock.patch.object(pkg, "_user_of", lambda p: "arthur"), \
                mock.patch.object(pkg, "_aur_pending", mock.Mock(side_effect=RPCError("no network"))):
            ups = pkg.listing(upgradable=True, aur=True)
        self.assertEqual(len(ups), 1)
        self.assertIn("AUR check failed", ups[0]["error"])


@unittest.skipUnless(shutil.which("gtk4-broadwayd"), "needs gtk4-broadwayd for a headless GTK display")
class StoreUI(unittest.TestCase):
    """The real Store window (fake package backend): partial update -> failure card + Retry -> up to date."""

    def test_partial_update_flow(self):
        disp = ":17"
        bd = subprocess.Popen(["gtk4-broadwayd", disp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            env = {**os.environ, "GDK_BACKEND": "broadway", "BROADWAY_DISPLAY": disp, "ARCLIGHT_STORE_FAKE": "1",
                   "ARCLIGHT_STORE_DEMO_FAIL": "update-aur", "ARCLIGHT_STORE_DEMO_SPEED": "20",
                   "SHOTS": os.environ.get("SHOTS", "")}
            p = subprocess.run([sys.executable, str(HERE / "ui/store_update_failure.py")], env=env,
                               capture_output=True, text=True, timeout=120)
        finally:
            bd.terminate()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("PASS", p.stdout)


if __name__ == "__main__":
    unittest.main()
