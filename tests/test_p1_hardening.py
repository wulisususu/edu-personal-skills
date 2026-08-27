import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "dingyi-edu-radar"
SCRAPER_PATH = SKILL_DIR / "scripts" / "scrape_snapshot.py"
SAFE_PUBLISH = SKILL_DIR / "scripts" / "safe_publish.py"


def load_scraper():
    spec = importlib.util.spec_from_file_location("scrape_snapshot_hardening", SCRAPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def verification():
    return {
        "status": "needs_review",
        "official_url": None,
        "official_domain": None,
        "candidate_url": None,
        "candidate_domain": None,
        "verified_at": None,
        "http_status": None,
        "method": "none",
    }


def write_stage(root: Path, snapshot_id: str = "symlink-test"):
    refs = root / "references"
    refs.mkdir(parents=True)
    (refs / "a.md").write_text("<!-- UNTRUSTED_EXTERNAL_DATA -->\n# a\n", encoding="utf-8")
    item = {
        "slug": "a",
        "title": "a",
        "kw": "a",
        "file": "references/a.md",
        "source_url": "https://www.edumails.cn/a.html",
        "source_kind": "benefit",
        "category": "other",
        "aliases": ["a"],
        "risk_flags": [],
        "risk_level": "low",
        "verification": verification(),
        "source_trust": "untrusted",
    }
    (root / "catalog.json").write_text(json.dumps([item]), encoding="utf-8")
    (root / "snapshot_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "snapshot_id": snapshot_id,
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
                "snapshot_id": snapshot_id,
                "total": 1,
                "status_counts": {"needs_review": 1},
                "category_counts": {"other": 1},
                "risk_level_counts": {"low": 1},
                "risk_flag_counts": {},
                "verified": 0,
                "candidate": 0,
                "needs_review": 1,
                "failed": 0,
            }
        ),
        encoding="utf-8",
    )


class SnapshotRootHardeningTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_snapshots_symlink_is_rejected_without_writing_outside_skill(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            skill = base / "skill"
            outside = base / "outside"
            skill.mkdir()
            outside.mkdir()
            (skill / "references").mkdir()
            (skill / "references" / "old.md").write_text("# old\n", encoding="utf-8")
            (skill / "catalog.json").write_text(
                json.dumps([{"slug": "old", "title": "old", "kw": "old", "file": "references/old.md"}]),
                encoding="utf-8",
            )
            (skill / "active_snapshot.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "snapshot_id": "bootstrap",
                        "snapshot_root": ".",
                        "catalog": "catalog.json",
                        "references": "references",
                        "activated_at": "bootstrap",
                        "catalog_schema_version": 2,
                    }
                ),
                encoding="utf-8",
            )
            (skill / ".snapshots").symlink_to(outside, target_is_directory=True)
            stage = skill / ".refresh-stage-test"
            write_stage(stage)
            before = (skill / "active_snapshot.json").read_text(encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SAFE_PUBLISH),
                    "--skill-dir",
                    str(skill),
                    "--stage-dir",
                    str(stage),
                    "--min-count",
                    "1",
                    "--min-ratio",
                    "0.8",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, (skill / "active_snapshot.json").read_text(encoding="utf-8"))
            self.assertFalse((outside / "symlink-test").exists())


class PaginationHardeningTests(unittest.TestCase):
    def test_repeated_listing_page_terminates_cleanly(self):
        scraper = load_scraper()
        base = "https://www.edumails.cn"
        page = f'<html><body><a href="{base}/one.html">one</a></body></html>' + ("x" * 1200)
        calls = []

        def fake_fetch(url, *, timeout, retries=3):
            calls.append(url)
            return 200, page

        original = scraper._fetch
        scraper._fetch = fake_fetch
        try:
            urls = scraper._crawl_category(base, "us", timeout=1, max_pages=10)
        finally:
            scraper._fetch = original

        self.assertEqual({f"{base}/one.html"}, urls)
        self.assertEqual(2, len(calls), "a repeated second page should terminate pagination")


if __name__ == "__main__":
    unittest.main()
