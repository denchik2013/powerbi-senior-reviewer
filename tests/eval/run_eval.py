"""Run one end-to-end review with headless Claude Code and grade it (stdlib only; needs the `claude` CLI).

Usage:
    python tests/eval/run_eval.py --fixture bad|good --workdir <empty dir> [--prompt "..."] [--model <id>]

Creates <workdir> as a git repo containing a copy of the fixture and this repo's .gitignore, runs
`claude -p <prompt> --plugin-dir <this repo>` inside it, saves the transcript to <workdir>/out/transcript.jsonl and prints the
grade from grade.py. Not part of the unit tests or CI: it calls a model and costs tokens.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from grade import grade  # noqa: E402

FIXTURES = {"bad": "BadModel", "good": "GoodModel"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", choices=FIXTURES, required=True)
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--prompt", default="review my Power BI project")
    ap.add_argument("--model")
    ap.add_argument("--max-turns", default="80")
    a = ap.parse_args(argv)

    wd = a.workdir.resolve()
    if wd.exists() and any(wd.iterdir()):
        sys.exit(f"{wd} is not empty")
    wd.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "tests" / "fixtures" / FIXTURES[a.fixture], wd / FIXTURES[a.fixture])
    shutil.copy(ROOT / ".gitignore", wd / ".gitignore")
    ident = ["-c", "user.name=eval", "-c", "user.email=eval@example.invalid"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=wd, check=True)
    subprocess.run(["git", "add", "-A"], cwd=wd, check=True)
    subprocess.run(["git", *ident, "commit", "-qm", "fixture"], cwd=wd, check=True)

    cmd = ["claude", "-p", a.prompt, "--plugin-dir", str(ROOT), "--output-format", "stream-json", "--verbose",
           "--max-turns", a.max_turns, "--permission-mode", "acceptEdits",
           "--allowedTools", "Bash Read Write Edit Glob Grep Skill"]
    if a.model:
        cmd += ["--model", a.model]
    (wd / "out").mkdir(exist_ok=True)  # git-ignored; keeps run artefacts out of the fixture check
    transcript = wd / "out" / "transcript.jsonl"
    with open(transcript, "w", encoding="utf-8") as log:
        subprocess.run(cmd, cwd=wd, stdout=log, stderr=subprocess.STDOUT)

    log_text = transcript.read_text(encoding="utf-8", errors="replace")
    skill_used = '"name":"Skill"' in log_text and "powerbi-senior-reviewer:powerbi-senior-reviewer" in log_text
    res = grade(wd, a.fixture)
    res["skillInvoked"] = skill_used
    print(json.dumps(res, indent=2, ensure_ascii=False))
    (wd / "out" / "grade.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
