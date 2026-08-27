from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
OLD_CI = REPO_ROOT / ".github" / "workflows" / "p0-tests.yml"


class PermanentCIContractTests(unittest.TestCase):
    def test_permanent_ci_covers_supported_runtime_and_validation_layers(self):
        self.assertTrue(CI.is_file(), "missing permanent .github/workflows/ci.yml")
        text = CI.read_text(encoding="utf-8")
        for required in (
            "push:",
            "pull_request:",
            '"3.11"',
            '"3.12"',
            "python -m unittest discover -s tests -v",
            "beautifulsoup4",
            "lxml",
            "fts5",
            "sqlite3",
            "json.load",
            "py_compile",
            "bash -n skills/dingyi-edu-radar/scripts/refresh.sh",
            "search.py",
            "refresh.py",
            "refresh.ps1",
            "ubuntu-latest",
            "macos-latest",
            "windows-latest",
            "test_parser_fixtures.py",
            "test_portable_refresh.py",
            "test_third_party_notices.py",
        ):
            self.assertIn(required, text)

    def test_temporary_p0_named_workflow_is_removed(self):
        self.assertFalse(OLD_CI.exists(), "temporary p0-tests.yml should be replaced by ci.yml")


if __name__ == "__main__":
    unittest.main()
