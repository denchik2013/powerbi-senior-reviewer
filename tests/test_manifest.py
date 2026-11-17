"""Validate plugin/marketplace manifests and SKILL.md frontmatter (stdlib only)."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "powerbi-senior-reviewer"

# Keys accepted by claude.ai upload / Skills API; anything else is a hard error there.
PORTABLE_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def read_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "frontmatter must start on line 1"
    end = text.index("\n---\n", 4)
    block, body = text[4:end], text[end + 5:]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:  # top-level key (nested metadata lines are indented and skipped)
            fields[m.group(1)] = m.group(2).strip()
    return fields, body


class ManifestTests(unittest.TestCase):
    def test_plugin_and_marketplace_agree(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertTrue(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", plugin["name"]))
        for key in ("name", "owner", "plugins"):
            self.assertIn(key, market)
        entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
        self.assertEqual(entry["source"], "./")
        self.assertEqual(entry.get("version"), plugin["version"])

    def test_skill_frontmatter_is_portable(self):
        fields, body = read_frontmatter(SKILL_DIR / "SKILL.md")
        self.assertLessEqual(set(fields), PORTABLE_KEYS, "non-portable frontmatter key")
        name = fields["name"]
        self.assertEqual(name, SKILL_DIR.name)
        self.assertLessEqual(len(name), 64)
        self.assertTrue(re.fullmatch(r"[a-z0-9-]+", name))
        self.assertNotRegex(name, "claude|anthropic")
        desc = fields["description"]
        self.assertTrue(0 < len(desc) <= 1024, f"description length {len(desc)}")
        self.assertNotRegex(desc, r"<[^>]+>", "no XML/angle-bracket tags in description")
        for bad in (": ", " #"):  # would break a YAML plain scalar
            self.assertNotIn(bad, desc)

    def test_skill_md_is_small(self):
        lines = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").count("\n")
        self.assertLessEqual(lines, 300, "keep SKILL.md short; move detail to references/")

    def test_description_mentions_trigger_terms(self):
        desc = read_frontmatter(SKILL_DIR / "SKILL.md")[0]["description"].lower()
        for term in ("review", "power bi", "pbip", "tmdl", "pbir", "dax", "pr", "semantic model", "best practices"):
            self.assertIn(term, desc)

    def test_every_static_rule_is_documented(self):
        import sys
        sys.path.insert(0, str(SKILL_DIR / "scripts"))
        from static_checks import RULES
        docs = "".join(p.read_text(encoding="utf-8") for p in (SKILL_DIR / "references").glob("rules-*.md"))
        missing = [rid for rid in RULES if f"### {rid} " not in docs]
        self.assertEqual(missing, [])

    def test_skill_md_links_existing_references(self):
        body = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for name in re.findall(r"`(?:references/)?((?:rules-[a-z-]+|custom-rules|review-template)\.md)`", body):
            self.assertTrue((SKILL_DIR / "references" / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
