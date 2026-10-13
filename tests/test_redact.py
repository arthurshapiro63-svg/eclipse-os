"""Bug 0.1.1-2: secrets must never reach Arclight's logs; logs are 0600."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from arclight import redact
from arclight.system import daemon

PW = "Synthetic-Pa55word!42"
PW2 = "hunter2-synthetic-xyz"
TOKEN = "sk-ant-api03-SYNTHETICsyntheticSYNTHETIC0123456789"


def log_calls(calls, logger_factory=daemon.make_logger):
    d = Path(tempfile.mkdtemp())
    path = d / "actions.jsonl"
    log = logger_factory(path)
    for method, params, err in calls:
        log(method, params, {"pid": os.getpid(), "uid": 1000}, None, err, 0.01)
    return path


class DaemonLog(unittest.TestCase):
    def test_user_add_and_mod_passwords(self):
        p = log_calls([("sys.user_add", {"name": "alice", "groups": ["video"], "password": PW, "admin": True}, None),
                       ("sys.user_mod", {"name": "alice", "password": PW2}, None)])
        text = p.read_text()
        self.assertNotIn(PW, text)
        self.assertNotIn(PW2, text)
        recs = [json.loads(l) for l in text.splitlines()]
        self.assertEqual(recs[0]["params"]["password"], "[redacted]")
        self.assertEqual(recs[0]["params"]["name"], "alice")          # diagnostics kept
        self.assertEqual(recs[0]["params"]["groups"], ["video"])
        self.assertEqual(recs[0]["method"], "sys.user_add")
        self.assertIn("agent", recs[0])

    def test_log_file_mode(self):
        p = log_calls([("sys.user_add", {"name": "a", "password": PW}, None)])
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_existing_world_readable_log_is_tightened(self):
        d = Path(tempfile.mkdtemp())
        p = d / "actions.jsonl"
        p.write_text("")
        p.chmod(0o644)
        daemon.make_logger(p)("sys.hostname", {"name": "box"}, {"pid": 1}, None, None, 0)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_exec_input_and_inline_secrets(self):
        calls = [
            ("exec", {"cmd": ["chpasswd"], "input": f"bob:{PW}\n"}, None),
            ("exec", {"cmd": f"echo 'bob:{PW2}' | chpasswd"}, None),
            ("exec", {"cmd": f"nmcli device wifi connect Home password {PW}"}, None),
            ("exec", {"cmd": f"curl -H 'Authorization: Bearer {TOKEN}' https://example.invalid"}, None),
            ("exec", {"cmd": f"git clone https://bob:{PW2}@example.invalid/r.git"}, None),
            ("exec", {"cmd": f"ANTHROPIC_API_KEY={TOKEN} claude -p hi"}, None),
            ("exec", {"cmd": f"mysql --password={PW} db"}, None),
        ]
        text = log_calls(calls).read_text()
        for s in (PW, PW2, TOKEN):
            self.assertNotIn(s, text)
        recs = [json.loads(l) for l in text.splitlines()]
        self.assertEqual(recs[0]["params"]["input"], f"[{len(PW) + 5} chars]")
        self.assertIn("nmcli device wifi connect Home password", recs[2]["params"]["cmd"])   # still readable

    def test_error_message_echoing_secret(self):
        p = log_calls([("sys.user_mod", {"name": "x", "password": PW}, {"message": f"chpasswd rejected {PW}"})])
        rec = json.loads(p.read_text())
        self.assertNotIn(PW, p.read_text())
        self.assertFalse(rec["ok"])
        self.assertIn("chpasswd rejected", rec["error"])

    def test_file_write_content_and_settings_value(self):
        p = log_calls([("file.write", {"path": "/etc/wpa.conf", "content": f"psk={PW}\n"}, None),
                       ("config.set", {"key": "wifi.psk", "value": PW2}, None),
                       ("file.edit", {"path": "/etc/x", "old": "a", "new": f"token: {TOKEN}"}, None)])
        text = p.read_text()
        for s in (PW, PW2, TOKEN):
            self.assertNotIn(s, text)
        self.assertIn("/etc/wpa.conf", text)

    def test_events_log_is_private(self):
        d = Path(tempfile.mkdtemp())
        with mock.patch.object(daemon, "LOG_DIR", d):
            api, _ = daemon.build_api()
        api.methods["events.add"]("test", f"password {PW}")
        ev = d / "events.jsonl"
        self.assertNotIn(PW, ev.read_text())
        self.assertEqual(stat.S_IMODE(ev.stat().st_mode), 0o600)


class SessionLog(unittest.TestCase):
    def test_typed_text_and_clipboard(self):
        p = log_calls([("input.type", {"text": PW}, None), ("clip.set", {"text": PW2}, None),
                       ("ui.set_text", {"name": "Password", "text": PW}, None),
                       ("input.sequence", {"steps": [{"type": "text", "text": PW}]}, None)])
        text = p.read_text()
        self.assertNotIn(PW, text)
        self.assertNotIn(PW2, text)
        self.assertIn(f"[{len(PW)} chars]", text)


class Scrub(unittest.TestCase):
    def test_scrub_existing_log(self):
        d = Path(tempfile.mkdtemp())
        p = d / "actions.jsonl"
        p.write_text(json.dumps({"method": "sys.user_add", "params": {"name": "a", "password": PW}}) + "\n" +
                     json.dumps({"method": "exec", "params": {"cmd": f"echo 'a:{PW2}' | chpasswd"}}) + "\n")
        p.chmod(0o644)
        self.assertEqual(redact.scrub_file(p), 2)
        self.assertNotIn(PW, p.read_text())
        self.assertNotIn(PW2, p.read_text())
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_crypt_hash_in_installer_command(self):
        line = "$ arch-chroot /mnt usermod -p '$6$saltsalt$abcdefghijklmnopqrstuvwxyz0123456789' alice"
        out = redact.scrub_text(line)
        self.assertNotIn("abcdefghijklmnop", out)
        self.assertIn("usermod -p", out)

    def test_ordinary_text_untouched(self):
        s = "pacman -S --noconfirm firefox && systemctl restart NetworkManager"
        self.assertEqual(redact.scrub_text(s), s)


if __name__ == "__main__":
    unittest.main()
