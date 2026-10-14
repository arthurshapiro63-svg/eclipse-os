"""Eclipse AI's command log really gets written (and masked): 0.1.1 shipped a broken import here that made every
logged command raise, which a VM test of the AI's root path found in 0.1.2."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from arclight.apps.eclipse_ai import config, store


class CommandLog(unittest.TestCase):
    def test_log_command_writes_a_private_masked_log(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "LOG_DIR", Path(d)):
            store.log_command("echo hi", 0, "password=hunter2 ok", "shell")
            f = Path(d, "commands.log")
            text = f.read_text()
            self.assertIn("echo hi", text)
            self.assertNotIn("hunter2", text)
            self.assertEqual(oct(os.stat(f).st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
