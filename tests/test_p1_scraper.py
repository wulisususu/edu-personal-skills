import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "dingyi-edu-radar" / "scripts" / "scrape_snapshot.py"


def load_scraper():
    if not SCRIPT.exists():
        raise AssertionError(f"missing implementation: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("scrape_snapshot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SafeScraperContractTests(unittest.TestCase):
    def test_category_membership_maps_to_real_source_kind(self):
        scraper = load_scraper()
        url = "https://www.edumails.cn/example.html"
        self.assertEqual("benefit", scraper.source_kind_for_url(url, {url}, set()))
        self.assertEqual("edu_mail", scraper.source_kind_for_url(url, set(), {url}))
        self.assertEqual("edu_mail", scraper.source_kind_for_url(url, {url}, {url}))

    def test_reference_markdown_has_explicit_untrusted_boundary(self):
        scraper = load_scraper()
        md = scraper.build_reference_markdown(
            title="Example",
            description="desc",
            source_url="https://www.edumails.cn/example.html",
            body="Body",
        )
        self.assertIn("UNTRUSTED_EXTERNAL_DATA", md)
        self.assertIn("BEGIN_UNTRUSTED_REFERENCE_DATA", md)
        self.assertIn("END_UNTRUSTED_REFERENCE_DATA", md)
        self.assertIn("来源: https://www.edumails.cn/example.html", md)


if __name__ == "__main__":
    unittest.main()
