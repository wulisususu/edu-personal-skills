import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "dingyi-edu-radar"
ENRICH = SKILL_DIR / "scripts" / "snapshot_enrich.py"


class SnapshotEnrichmentTests(unittest.TestCase):
    def test_offline_enrichment_builds_catalog_manifest_and_verification_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            refs = root / "references"
            refs.mkdir()
            (refs / "github.md").write_text(
                "<!-- UNTRUSTED_EXTERNAL_DATA -->\n# GitHub\n[official](https://github.com/education/students)\n",
                encoding="utf-8",
            )
            (root / "catalog.json").write_text(
                json.dumps(
                    [
                        {
                            "slug": "github",
                            "title": "GitHub Copilot 学生教育优惠",
                            "kw": "GitHub Copilot",
                            "file": "references/github.md",
                            "source_url": "https://www.edumails.cn/github.html",
                            "source_kind": "benefit",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ENRICH),
                    "--snapshot-root",
                    str(root),
                    "--snapshot-id",
                    "fixture-001",
                    "--offline",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
            item = catalog[0]
            self.assertEqual("developer-tools", item["category"])
            self.assertIn("GitHub", item["aliases"])
            self.assertIn(item["verification"]["status"], {"candidate", "needs_review"})
            self.assertNotEqual("verified", item["verification"]["status"])
            manifest = json.loads((root / "snapshot_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("fixture-001", manifest["snapshot_id"])
            self.assertEqual(1, manifest["catalog_count"])
            report = json.loads((root / "verification_report.json").read_text(encoding="utf-8"))
            self.assertEqual("fixture-001", report["snapshot_id"])
            self.assertEqual(1, report["total"])


class RefreshPipelineWiringTests(unittest.TestCase):
    def test_refresh_runs_structured_enrichment_before_safe_publish(self):
        text = (SKILL_DIR / "scripts" / "refresh.sh").read_text(encoding="utf-8")
        self.assertIn("snapshot_enrich.py", text)
        self.assertIn("SNAPSHOT_ID", text)
        self.assertIn("source_kind", text)
        self.assertIn("--verify-official", text)
        self.assertLess(text.index("snapshot_enrich.py"), text.index("safe_publish.py"))

    def test_skill_resolves_active_snapshot_and_uses_v2_metadata(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for token in ("active_snapshot.json", "category", "aliases", "risk_flags", "verification.status"):
            self.assertIn(token, text)
        self.assertIn("bootstrap", text)

    def test_runtime_snapshots_are_gitignored(self):
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".snapshots/", text)
        self.assertIn(".refresh-stage.", text)


if __name__ == "__main__":
    unittest.main()
