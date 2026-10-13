"""Bugs 0.1.1-5/6/7: live boot without the pam_systemd deadlock, console font, the Rite's pacman.conf."""
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from arclight_installer import engine as engmod
from arclight_installer import rite_auto

ROOT = _paths.ROOT
PROFILE = ROOT / "profile"
INSTALLER = ROOT / "src/eclipse-os-installer"


class LiveSetup(unittest.TestCase):
    """5: the live-user unit runs Before=systemd-user-sessions; it must not open a PAM login session."""

    def test_no_pam_session_in_live_setup(self):
        script = (PROFILE / "airootfs/usr/local/bin/arclight-live-setup").read_text()
        code = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotRegex(code, r"\b(runuser|su|sudo|machinectl|systemd-run)\b")
        self.assertRegex(code, r"setpriv --reuid \"\$U\".*--init-groups")
        unit = (PROFILE / "airootfs/etc/systemd/system/arclight-live-setup.service").read_text()
        self.assertIn("Before=getty@tty1.service systemd-user-sessions.service", unit)

    def test_script_is_valid_bash(self):
        subprocess.run(["bash", "-n", str(PROFILE / "airootfs/usr/local/bin/arclight-live-setup")], check=True)


class ConsoleFont(unittest.TestCase):
    """6: FONT= only names an installed font; terminus-font ships on the ISO and with eclipse-os-core."""

    def test_font_written_only_when_present(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(engmod.vconsole_conf(root, "de"), "KEYMAP=de\n")
        f = root / "usr/share/kbd/consolefonts/ter-v20b.psf.gz"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"x")
        self.assertEqual(engmod.vconsole_conf(root, None), "KEYMAP=us\nFONT=ter-v20b\n")

    def test_vconsole_setup_retries_transient_failures(self):
        conf = ROOT / "src/eclipse-os-core/root/usr/lib/systemd/system/systemd-vconsole-setup.service.d/50-eclipse-retry.conf"
        text = conf.read_text()
        self.assertIn("Restart=on-failure", text)
        self.assertRegex(text, r"StartLimitBurst=\d+")

    def test_terminus_font_is_installed(self):
        self.assertIn("terminus-font", (PROFILE / "packages.x86_64").read_text().split())
        self.assertIn("'terminus-font'", (ROOT / "src/eclipse-os-core/PKGBUILD").read_text())


class RitePacmanConf(unittest.TestCase):
    """7: the Rite's pacman.conf exists, and its [eclipse] repo is put on the ISO by build-iso.sh."""
    CONF = INSTALLER / "root/etc/arclight-rite/pacman.conf"

    def test_conf_shipped_where_the_rite_looks(self):
        used = set(re.findall(r"-C (\S+)", Path(rite_auto.__file__).read_text()))
        self.assertEqual(used, {"/etc/arclight-rite/pacman.conf"})
        self.assertTrue(self.CONF.is_file())
        text = self.CONF.read_text()
        for repo in ("[core]", "[extra]", "[eclipse]"):
            self.assertIn(repo, text)
        self.assertIn("Server = file:///opt/eclipse-repo", text)
        self.assertNotIn("@REPO@", text)

    def test_build_puts_repo_on_the_iso(self):
        build = (ROOT / "tools/build-iso.sh").read_text()
        self.assertIn('"$W/airootfs/opt/eclipse-repo"', build)
        self.assertIn("eclipse.db", build)

    def test_rite_packages_from_the_repo_exist(self):
        with tarfile.open(ROOT / "repo/eclipse.db.tar.gz") as t:
            have = {m.name.split("/")[0].rsplit("-", 2)[0] for m in t.getmembers() if m.isdir()}
        for n in (4, 11):
            for cmd in rite_auto.plan(n, {"facts": {"disk": "/dev/vda", "user": "x"}})[0]:
                for pkg in re.findall(r"\beclipse-os-[a-z]+\b", cmd):
                    self.assertIn(pkg, have, cmd)


if __name__ == "__main__":
    unittest.main()
