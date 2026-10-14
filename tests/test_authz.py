"""0.1.2 fix 1: arclightd changes need the administrator password (polkit), reading stays open, the live USB /
opt-in passwordless pair is written and removed cleanly, and an AI cannot approve its own root action."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _paths  # noqa: F401
from arclight.rpc import RPCError
from arclight.system import authz, sysconf

ME = {"pid": os.getpid(), "uid": 1000, "gid": 1000}
CORE = _paths.CORE.parent.parent.parent   # .../eclipse-os-core/root


class Policy(unittest.TestCase):
    def test_reading_is_open(self):
        for m in ("pkg.search", "svc.status", "log.query", "sys.info", "snap.list", "pkg.repo"):
            self.assertFalse(authz.needs_admin(m, {}, ME), m)

    def test_changes_need_admin(self):
        for m, p in (("exec", {"cmd": ["true"]}), ("pkg.install", {"names": ["x"]}), ("svc.restart", {"name": "x"}),
                     ("file.write", {"path": "/etc/x", "content": ""}), ("snap.create", {}), ("power.reboot", {}),
                     ("sys.nopasswd", {"enable": True}), ("config.set", {"key": "a", "value": 1}),
                     ("sys.timezone", {"tz": "UTC"}), ("sys.hostname", {"name": "x"})):
            self.assertTrue(authz.needs_admin(m, p, ME), m)

    def test_getters_without_change_params_are_open(self):
        self.assertFalse(authz.needs_admin("sys.timezone", {}, ME))
        self.assertFalse(authz.needs_admin("sys.nopasswd", {}, ME))
        self.assertFalse(authz.needs_admin("sys.sysctl", {"key": "vm.swappiness"}, ME))

    def test_root_caller_is_never_asked(self):
        self.assertFalse(authz.needs_admin("exec", {"cmd": ["true"]}, {"pid": 1, "uid": 0, "gid": 0}))

    def test_unknown_method_needs_admin(self):
        self.assertTrue(authz.needs_admin("something.new", {}, ME))

    def test_file_read_only_open_when_the_caller_could_read_it(self):
        with mock.patch.object(authz, "_caller_can_read", return_value=False):
            self.assertTrue(authz.needs_admin("file.read", {"path": "/etc/shadow"}, ME))
        with mock.patch.object(authz, "_caller_can_read", return_value=True):
            self.assertFalse(authz.needs_admin("file.read", {"path": "/etc/hostname"}, ME))
            self.assertFalse(authz.needs_admin("file.list", {"path": "/etc"}, ME))
        with mock.patch.object(authz, "_caller_can_read", return_value=False):
            self.assertTrue(authz.needs_admin("file.list", {"path": "/root"}, ME))
            self.assertTrue(authz.needs_admin("file.stat", {"path": "/root/x"}, ME))
        self.assertTrue(authz.needs_admin("pkg.repo", {"conf": "/etc/shadow"}, ME))


class Pkcheck(unittest.TestCase):
    def _run(self, code, interactive=True):
        seen = {}

        def fake(cmd, **kw):
            seen["cmd"] = cmd
            return SimpleNamespace(returncode=code, stdout="", stderr="")
        with mock.patch.object(authz.subprocess, "run", side_effect=fake):
            try:
                authz.authorize("pkg.install", {"names": ["x"]}, ME, interactive)
                return None, seen["cmd"]
            except RPCError as e:
                return str(e), seen["cmd"]

    def test_yes_from_polkit_allows(self):
        err, cmd = self._run(0)
        self.assertIsNone(err)
        self.assertIn("dev.arclight.admin", cmd)
        self.assertIn("--allow-user-interaction", cmd)
        self.assertIn(f"{os.getpid()},", " ".join(cmd))

    def test_cancelled_or_failed_refuses(self):
        self.assertIn("cancelled", self._run(3)[0])
        self.assertIn("not allowed", self._run(1)[0])

    def test_power_follows_logind_rules(self):
        seen = {}

        def fake(cmd, **kw):
            seen["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(authz.subprocess, "run", side_effect=fake):
            authz.authorize("sys.power", {"action": "reboot"}, ME)
        self.assertIn("org.freedesktop.login1.reboot", seen["cmd"])
        self.assertNotIn("dev.arclight.admin", seen["cmd"])

    def test_background_calls_never_pop_up(self):
        err, cmd = self._run(2, interactive=False)
        self.assertNotIn("--allow-user-interaction", cmd)
        self.assertIn("background", err)

    def test_open_call_does_not_ask_polkit(self):
        with mock.patch.object(authz.subprocess, "run", side_effect=AssertionError("asked")):
            authz.authorize("pkg.search", {"query": "x"}, ME)


class PromptText(unittest.TestCase):
    """The password prompt names exactly what will happen, built from the real request."""

    def test_eclipse_ai_batch_shows_its_commands(self):
        from arclight.apps.eclipse_ai import elevate
        sc = elevate.build_script(["pacman -S --noconfirm htop", "touch /root/x"], "abcd1234", 120, "/run/user/1000/x.log")
        self.assertEqual(authz.describe("exec", {"cmd": ["/usr/bin/bash", "-c", sc]}),
                         "run as root: pacman -S --noconfirm htop ; touch /root/x")

    def test_a_doctored_batch_is_shown_raw(self):
        from arclight.apps.eclipse_ai import elevate
        sc = elevate.build_script(["true"], "abcd1234", 120, "/run/user/1000/x.log")
        for evil in (sc.replace("LANG=C.UTF-8", "LANG=C.UTF-8; rm -rf /"),
                     sc.replace("run() {", "run() { rm -rf /;"), sc + "\nrm -rf /\n"):
            self.assertTrue(authz.describe("exec", {"cmd": ["/usr/bin/bash", "-c", evil]}).startswith("run as root: set -u"))

    def test_secrets_never_reach_the_prompt(self):
        self.assertNotIn("hunter2", authz.describe("sys.user_mod", {"name": "bob", "password": "hunter2"}))

    def test_prompt_carries_the_summary(self):
        seen = {}

        def fake(cmd, **kw):
            seen["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(authz.subprocess, "run", side_effect=fake):
            authz.authorize("sys.nopasswd", {"enable": True}, ME)
        i = seen["cmd"].index("summary")
        self.assertIn("passwordless admin", seen["cmd"][i + 1])
        pol = (CORE / "usr/share/polkit-1/actions/dev.arclight.admin.policy").read_text()
        self.assertIn("$(summary)", pol)


class JobToken(unittest.TestCase):
    def test_token_runs_only_pacman_and_only_while_the_job_runs(self):
        t = authz.job_token()
        with mock.patch.object(authz.subprocess, "run", side_effect=AssertionError("asked")):
            authz.authorize("exec", {"cmd": ["pacman", "-U", "x.pkg.tar.zst"], "_job_token": t}, ME)
            with self.assertRaises(RPCError):
                authz.authorize("exec", {"cmd": ["bash", "-c", "id"], "_job_token": t}, ME)
            with self.assertRaises(RPCError):
                authz.authorize("exec", {"cmd": ["pacman"], "_job_token": "0" * 48}, ME)
        authz.drop_token(t)
        with mock.patch.object(authz.subprocess, "run", side_effect=AssertionError("asked")):
            with self.assertRaises(RPCError):
                authz.authorize("exec", {"cmd": ["pacman", "-U", "x"], "_job_token": t}, ME)


class Dispatcher(unittest.TestCase):
    def test_hook_runs_before_the_method_and_strips_interactive(self):
        import asyncio
        from arclight import rpc
        api = rpc.API("test")
        ran, asked = [], []

        @api.method("pkg.install")
        def install(names):
            ran.append(names)
            return "ok"

        def hook(method, params, peer, interactive=True):
            asked.append((method, dict(params), interactive))
            raise RPCError("not allowed: no")
        api.authorize = hook
        async def go():
            return await api.dispatch({"id": 1, "method": "pkg.install",
                                       "params": {"names": ["x"], "_interactive": False}}, ME, asyncio.get_running_loop())
        out = asyncio.run(go())
        self.assertEqual(ran, [])
        self.assertEqual(asked, [("pkg.install", {"names": ["x"]}, False)])
        self.assertIn("error", out)


class Files(unittest.TestCase):
    def test_package_defaults_ask_for_a_password(self):
        s = (CORE / "etc/sudoers.d/10-arclight").read_text()
        self.assertNotIn("NOPASSWD", s)
        self.assertIn("%arclight ALL=(ALL:ALL) ALL", s)
        self.assertFalse((CORE / "usr/share/polkit-1/rules.d/49-arclight.rules").exists())
        pol = (CORE / "usr/share/polkit-1/actions/dev.arclight.admin.policy").read_text()
        self.assertIn("<allow_active>auth_admin</allow_active>", pol)
        self.assertNotIn("auth_admin_keep", pol)
        self.assertNotIn("<allow_active>yes", pol)

    def test_optin_pair_is_written_checked_and_removed(self):
        with tempfile.TemporaryDirectory() as d:
            for sub in ("etc/sudoers.d", "etc/polkit-1/rules.d"):
                Path(d, sub).mkdir(parents=True)
            with mock.patch.object(sysconf.subprocess, "run", wraps=subprocess.run) as run:
                if subprocess.run(["which", "visudo"], capture_output=True).returncode != 0:
                    run.side_effect = lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr="")
                self.assertEqual(sysconf.set_nopasswd(True, d), {"enabled": True})
            s = Path(d, sysconf.NOPASSWD_SUDOERS)
            self.assertEqual(oct(s.stat().st_mode & 0o777), "0o440")
            self.assertIn("NOPASSWD: ALL", s.read_text())
            self.assertIn("polkit.Result.YES", Path(d, sysconf.NOPASSWD_POLKIT).read_text())
            self.assertEqual(sysconf.set_nopasswd(False, d), {"enabled": False})
            self.assertFalse(s.exists() or Path(d, sysconf.NOPASSWD_POLKIT).exists())

    def test_sorts_after_the_package_rule(self):
        self.assertGreater(Path(sysconf.NOPASSWD_SUDOERS).name, "10-arclight")


class SelfApproval(unittest.TestCase):
    """The AI must not be able to click its own 'yes'."""

    def test_session_daemon_marks_injection_before_it_happens(self):
        from arclight.session import daemon
        api = daemon.build_api()
        daemon._INJECTED["last"] = None
        api.authorize("input.click", {"x": 1, "y": 1}, ME)
        self.assertIsNotNone(daemon._INJECTED["last"])
        api.authorize("win.list", {}, ME)   # reading does not count
        self.assertLess(api.methods["session.input_activity"]()["seconds_since"], 5)

    def test_yes_is_refused_right_after_injected_input(self):
        from arclight.apps.eclipse_ai import ui
        with mock.patch("arclight.client.call", return_value={"seconds_since": 0.4}):
            self.assertTrue(ui.ai_input_recent())
        with mock.patch("arclight.client.call", return_value={"seconds_since": 30.0}):
            self.assertFalse(ui.ai_input_recent())
        with mock.patch("arclight.client.call", return_value={"seconds_since": None}):
            self.assertFalse(ui.ai_input_recent())


@unittest.skipUnless(shutil.which("gtk4-broadwayd"), "needs gtk4-broadwayd for a headless GTK display")
class CardAndSettingsUI(unittest.TestCase):
    def test_real_widgets(self):
        disp = ":18"
        bd = subprocess.Popen(["gtk4-broadwayd", disp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            env = {**os.environ, "GDK_BACKEND": "broadway", "BROADWAY_DISPLAY": disp, "SHOTS": os.environ.get("SHOTS", "")}
            p = subprocess.run([sys.executable, str(Path(__file__).parent / "ui/approval_and_admin.py")], env=env,
                               capture_output=True, text=True, timeout=120)
        finally:
            bd.terminate()
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
        self.assertIn("PASS", p.stdout)


if __name__ == "__main__":
    unittest.main()
