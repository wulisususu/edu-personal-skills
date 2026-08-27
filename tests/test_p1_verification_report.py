import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "dingyi-edu-radar" / "scripts" / "snapshot_validate.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("snapshot_validate_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def item(slug="a"):
    return {
        "slug": slug,
        "title": slug,
        "kw": slug,
        "file": f"references/{slug}.md",
        "source_url": f"https://www.edumails.cn/{slug}.html",
        "source_kind": "benefit",
        "category": "other",
        "aliases": [slug],
        "risk_flags": [],
        "risk_level": "low",
        "source_trust": "untrusted",
        "verification": {
            "status": "needs_review",
            "official_url": None,
            "official_domain": None,
            "candidate_url": None,
            "candidate_domain": None,
            "verified_at": None,
            "http_status": None,
            "method": "none",
        },
    }


class VerificationReportValidationTests(unittest.TestCase):
    def setUp(self):
        self.validator = load_validator()

    def write_snapshot(self, root: Path, report_total: int):
        refs = root / "references"
        refs.mkdir()
        (refs / "a.md").write_text("<!-- UNTRUSTED_EXTERNAL_DATA -->\n# a\n", encoding="utf-8")
        (root / "catalog.json").write_text(json.dumps([item()]), encoding="utf-8")
        (root / "snapshot_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "snapshot_id": "report-test",
                    "catalog_count": 1,
                    "reference_count": 1,
                    "generated_at": "2026-08-27T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        (root / "verification_report.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "snapshot_id": "report-test",
                    "total": report_total,
                    "status_counts": {"needs_review": report_total},
                    "verified": 0,
                    "candidate": 0,
                    "needs_review": report_total,
                    "failed": 0,
                }
            ),
            encoding="utf-8",
        )

    def test_report_total_must_match_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_snapshot(root, report_total=9)
            with self.assertRaises(self.validator.SnapshotValidationError):
                self.validator.validate_snapshot(root, 1, 0, 0.8, False)

    def test_consistent_report_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_snapshot(root, report_total=1)
            result = self.validator.validate_snapshot(root, 1, 0, 0.8, False)
            self.assertEqual(1, result["reference_count"])


if __name__ == "__main__":
    unittest.main()
