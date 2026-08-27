import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "dingyi-edu-radar"
SCRIPTS = SKILL_DIR / "scripts"
SCRAPER = SCRIPTS / "scrape_snapshot.py"
SAFE_PUBLISH = SCRIPTS / "safe_publish.py"


def load_scraper():
    spec = importlib.util.spec_from_file_location("scraper_notices", SCRAPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_safe_publish():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("safe_publish_notices", SAFE_PUBLISH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class ThirdPartyNoticeTests(unittest.TestCase):
    def test_root_notice_explicitly_excludes_scraped_content_from_mit_grant(self):
        notice = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
        self.assertTrue(notice.is_file(), "missing THIRD_PARTY_NOTICES.md")
        text = notice.read_text(encoding="utf-8").casefold()
        self.assertIn("edumails.cn", text)
        self.assertIn("not licensed under", text)
        self.assertIn("mit", text)
        self.assertIn("original", text)

    def test_references_directory_has_local_copyright_boundary_notice(self):
        notice = SKILL_DIR / "references" / "README.md"
        self.assertTrue(notice.is_file(), "references/README.md must explain content licensing")
        text = notice.read_text(encoding="utf-8").casefold()
        self.assertIn("third-party", text)
        self.assertIn("not licensed under", text)
        self.assertIn("mit", text)
        self.assertIn("third_party_notices.md", text)

    def test_readme_license_section_distinguishes_code_from_scraped_content(self):
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8").casefold()
        self.assertIn("third_party_notices.md", text)
        self.assertIn("source code", text)
        self.assertIn("scraped", text)
        self.assertIn("not licensed under", text)

    def test_new_reference_header_carries_provenance_and_license_boundary(self):
        scraper = load_scraper()
        output = scraper.build_reference_markdown(
            title="Synthetic fixture",
            description="Synthetic description",
            source_url="https://www.edumails.cn/synthetic.html",
            body="Synthetic body",
        )
        self.assertIn("THIRD_PARTY_CONTENT", output)
        self.assertIn("not licensed under this repository's MIT license", output)
        self.assertIn("https://www.edumails.cn/synthetic.html", output)
        self.assertIn("BEGIN_UNTRUSTED_REFERENCE_DATA", output)
        self.assertIn("END_UNTRUSTED_REFERENCE_DATA", output)

    def test_references_readme_is_not_counted_as_bootstrap_article(self):
        safe_publish = load_safe_publish()
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skill"
            refs = skill / "references"
            refs.mkdir(parents=True)
            (refs / "README.md").write_text("notice\n", encoding="utf-8")
            for name in ("a", "b"):
                (refs / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill / "catalog.json").write_text(
                json.dumps(
                    [
                        {"slug": "a", "title": "a", "kw": "a", "file": "references/a.md"},
                        {"slug": "b", "title": "b", "kw": "b", "file": "references/b.md"},
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(2, safe_publish._count_root_bootstrap(skill))


if __name__ == "__main__":
    unittest.main()
