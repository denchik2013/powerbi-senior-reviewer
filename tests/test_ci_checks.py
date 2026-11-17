"""The CI guard scripts themselves must work: skill scripts pass, planted network code fails."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

CHECKS = helpers.ROOT / ".github" / "scripts"


def run(script: str, target: Path) -> int:
    return subprocess.run([sys.executable, str(CHECKS / script), str(target)], capture_output=True).returncode


class CiGuardTests(unittest.TestCase):
    def test_skill_scripts_pass(self):
        skills = helpers.ROOT / "skills"
        self.assertEqual(run("check_no_network.py", skills), 0)
        self.assertEqual(run("check_stdlib_only.py", skills), 0)

    def test_planted_network_code_fails(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            for i, code in enumerate(["import socket\n", "from urllib import request\n",
                                      "__import__('http.client')\n", "x = 'https://example.com'\n"]):
                d = Path(tmp) / str(i)
                d.mkdir()
                (d / "bad.py").write_text(code, encoding="utf-8")
                self.assertEqual(run("check_no_network.py", d), 1, code)

    def test_third_party_import_fails(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            (Path(tmp) / "bad.py").write_text("import requests\n", encoding="utf-8")
            self.assertEqual(run("check_stdlib_only.py", Path(tmp)), 1)


if __name__ == "__main__":
    unittest.main()
