import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "dingyi-edu-radar"


class BootstrapCatalogV2Tests(unittest.TestCase):
    def test_checked_in_bootstrap_catalog_is_v2_and_structured(self):
        catalog = json.loads((SKILL_DIR / "catalog.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(catalog), 200)
        required = {
            "slug", "title", "kw", "file", "source_url", "source_kind",
            "category", "aliases", "risk_flags", "risk_level", "verification", "source_trust",
        }
        for index, item in enumerate(catalog):
            self.assertTrue(required.issubset(item), f"item {index} missing v2 fields")
            self.assertIn(item["source_kind"], {"benefit", "edu_mail"})
            self.assertIsInstance(item["aliases"], list)
            self.assertIsInstance(item["risk_flags"], list)
            self.assertEqual("untrusted", item["source_trust"])
            self.assertIn(item["verification"]["status"], {"verified", "candidate", "needs_review", "failed"})

        kinds = {item["source_kind"] for item in catalog}
        self.assertEqual({"benefit", "edu_mail"}, kinds)
        self.assertTrue(any(item["risk_flags"] for item in catalog), "bootstrap risk scan must flag real source content")
        self.assertTrue(any(item["risk_level"] == "high" for item in catalog), "expected at least one high-risk source article")

    def test_bootstrap_pointer_declares_catalog_v2(self):
        pointer = json.loads((SKILL_DIR / "active_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual("bootstrap", pointer["snapshot_id"])
        self.assertEqual(2, pointer["catalog_schema_version"])


if __name__ == "__main__":
    unittest.main()
