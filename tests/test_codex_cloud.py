"""0.1.2 fix 2: the cloud model is named honestly, says that messages leave the computer, and is only offered when
the Codex CLI is installed and signed in."""
import unittest
from types import SimpleNamespace
from unittest import mock

import _paths  # noqa: F401
from arclight.apps.eclipse_ai import config, ultra


class Naming(unittest.TestCase):
    def test_honest_name_everywhere(self):
        self.assertEqual(ultra.NAME, "Codex (cloud)")
        self.assertEqual(config.display_name({}, "ultra"), "Codex (cloud)")
        # an older config that still says "Eclipse Totality" does not rename it
        self.assertEqual(config.display_name({"model_names": {"ultra": "Eclipse Totality"}}, "ultra"), "Codex (cloud)")
        self.assertNotIn("ultra", config.MODEL_NAMES)

    def test_no_disguise_left(self):
        src = open(ultra.__file__).read()
        for word in ("disguise", "Totality", "Never name any other model"):
            self.assertNotIn(word, src)
        self.assertIn("OpenAI", ultra.CLOUD_NOTE)
        self.assertIn("without approval cards", ultra.CLOUD_NOTE)
        self.assertIn("Codex by OpenAI", ultra._rules(False))

    def test_picker_hint_says_it_leaves_the_computer(self):
        import ast
        tree = ast.parse(open(ultra.__file__.replace("ultra.py", "ui.py")).read())
        hints = next(ast.literal_eval(n.value) for n in tree.body
                     if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "MODEL_HINTS")
        self.assertIn("leave this computer", hints["ultra"])


class Availability(unittest.TestCase):
    def setUp(self):
        ultra._STATUS.update(t=0.0, ok=False)

    def _avail(self, which, code, out):
        with mock.patch.object(ultra.shutil, "which", return_value=which), \
             mock.patch.object(ultra.subprocess, "run", return_value=SimpleNamespace(returncode=code, stdout=out, stderr="")):
            return ultra.available()

    def test_not_installed(self):
        self.assertFalse(self._avail(None, 0, "Logged in using ChatGPT"))

    def test_installed_not_signed_in(self):
        self.assertFalse(self._avail("/usr/bin/codex", 1, "Not logged in"))

    def test_installed_and_signed_in(self):
        self.assertTrue(self._avail("/usr/bin/codex", 0, "Logged in using ChatGPT"))


if __name__ == "__main__":
    unittest.main()
