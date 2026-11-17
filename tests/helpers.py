"""Shared test helpers: put the skill scripts on sys.path and locate fixtures."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "powerbi-senior-reviewer" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures"
BAD = FIXTURES / "BadModel"
GOOD = FIXTURES / "GoodModel"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

HAS_GIT = shutil.which("git") is not None


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=test",
                          "-c", "commit.gpgsign=false", *args],
                         cwd=str(cwd), capture_output=True, text=True, check=True)
    return out.stdout
