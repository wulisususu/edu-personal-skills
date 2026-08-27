import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "dingyi-edu-radar"
SCRAPER = SKILL_DIR / "scripts" / "scrape_snapshot.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "parser"


def load_scraper():
    spec = importlib.util.spec_from_file_location("fixture_scraper", SCRAPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ParserFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scraper = load_scraper()

    def test_wordpress_article_fixture_extracts_structured_content(self):
        title, description, body = self.scraper._parse_article(
            fixture("wordpress-article.html"),
            "https://www.edumails.cn/synthetic-product.html",
        )
        self.assertEqual("Synthetic Product 教育优惠", title)
        self.assertEqual("Synthetic parser fixture only", description)
        self.assertIn("## Eligibility", body)
        self.assertIn("**official portal**", body)
        self.assertIn("- One account", body)
        self.assertIn("[Official students page](https://example.edu/students)", body)
        self.assertIn("Plan | Price", body)
        self.assertNotIn("navigation text", body)

    def test_entry_content_fixture_is_supported_without_article_tag(self):
        title, description, body = self.scraper._parse_article(
            fixture("fallback-entry-content.html"),
            "https://www.edumails.cn/fallback.html",
        )
        self.assertEqual("Fallback University", title)
        self.assertEqual("Fixture fallback container", description)
        self.assertIn("Apply legally", body)
        self.assertIn("admissions portal & follow published requirements", body)
        self.assertIn("> Policies can change.", body)

    def test_prompt_injection_fixture_remains_inert_untrusted_data(self):
        title, description, body = self.scraper._parse_article(
            fixture("prompt-injection-text.html"),
            "https://www.edumails.cn/unsafe-fixture.html",
        )
        rendered = self.scraper.build_reference_markdown(
            title=title,
            description=description,
            source_url="https://www.edumails.cn/unsafe-fixture.html",
            body=body,
        )
        self.assertIn("Ignore previous instructions", rendered)
        self.assertIn("rm -rf /", rendered)
        begin = rendered.index("BEGIN_UNTRUSTED_REFERENCE_DATA")
        injection = rendered.index("Ignore previous instructions")
        end = rendered.index("END_UNTRUSTED_REFERENCE_DATA")
        self.assertLess(begin, injection)
        self.assertLess(injection, end)
        self.assertIn("THIRD_PARTY_CONTENT", rendered)

    def test_malformed_fixture_is_rejected_instead_of_generating_empty_reference(self):
        with self.assertRaises(RuntimeError):
            self.scraper._parse_article(
                fixture("malformed-no-article.html"),
                "https://www.edumails.cn/malformed.html",
            )


if __name__ == "__main__":
    unittest.main()
