import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "dingyi-edu-radar"
SCRIPTS = SKILL_DIR / "scripts"
PATHS_MODULE = SCRIPTS / "reference_paths.py"
MIGRATOR = SCRIPTS / "migrate_reference_filenames.py"


def load_module(path: Path, name: str):
    if not path.is_file():
        raise AssertionError(f"missing implementation: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ReferenceFilenameTests(unittest.TestCase):
    def test_short_safe_slug_stays_human_readable(self):
        paths = load_module(PATHS_MODULE, "reference_paths_short")
        self.assertEqual("replit.md", paths.reference_filename("replit"))
        self.assertEqual("github-copilot.md", paths.reference_filename("github-copilot"))

    def test_long_percent_encoded_slug_is_deterministically_shortened(self):
        paths = load_module(PATHS_MODULE, "reference_paths_long")
        slug = "%e7%be%8e%e5%9b%bd" * 40
        first = paths.reference_filename(slug)
        second = paths.reference_filename(slug)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^ref-[0-9a-f]{24}\.md$")
        self.assertLessEqual(len(first.encode("utf-8")), 80)

    def test_windows_reserved_basename_is_never_emitted(self):
        paths = load_module(PATHS_MODULE, "reference_paths_reserved")
        for slug in ("con", "PRN", "aux", "nul", "com1", "LPT9"):
            filename = paths.reference_filename(slug)
            self.assertTrue(filename.startswith("ref-"), (slug, filename))

    def test_bootstrap_catalog_uses_windows_safe_component_lengths(self):
        paths = load_module(PATHS_MODULE, "reference_paths_bootstrap")
        catalog = json.loads((SKILL_DIR / "catalog.json").read_text(encoding="utf-8"))
        for item in catalog:
            basename = Path(item["file"]).name
            self.assertLessEqual(len(basename.encode("utf-8")), paths.MAX_FILENAME_BYTES, item["file"])
            self.assertEqual(basename, paths.reference_filename(item["slug"]), item["slug"])
            self.assertTrue((SKILL_DIR / item["file"]).is_file(), item["file"])


class ReferenceFilenameMigrationTests(unittest.TestCase):
    def test_migration_renames_only_data_files_and_updates_catalog(self):
        migrator = load_module(MIGRATOR, "reference_filename_migrator")
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skill"
            refs = skill / "references"
            refs.mkdir(parents=True)
            # Long enough to exceed the portable 120-byte policy while still being
            # creatable on POSIX filesystems for this migration fixture.
            long_slug = "%e7%be%8e%e5%9b%bd" * 8
            (refs / "README.md").write_text("notice\n", encoding="utf-8")
            (refs / "replit.md").write_text("# replit\n", encoding="utf-8")
            (refs / f"{long_slug}.md").write_text("# long\n", encoding="utf-8")
            catalog = [
                {"slug": "replit", "title": "Replit", "kw": "Replit", "file": "references/replit.md"},
                {"slug": long_slug, "title": "Long", "kw": "Long", "file": f"references/{long_slug}.md"},
            ]
            (skill / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

            changed = migrator.migrate(skill)

            self.assertEqual(1, changed)
            migrated = json.loads((skill / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual("references/replit.md", migrated[0]["file"])
            self.assertRegex(migrated[1]["file"], r"^references/ref-[0-9a-f]{24}\.md$")
            self.assertFalse((refs / f"{long_slug}.md").exists())
            self.assertTrue((skill / migrated[1]["file"]).is_file())
            self.assertTrue((refs / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
