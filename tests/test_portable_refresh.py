import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "dingyi-edu-radar"
SCRIPTS = SKILL_DIR / "scripts"
REFRESH_PY = SCRIPTS / "refresh.py"
REFRESH_SH = SCRIPTS / "refresh.sh"
REFRESH_PS1 = SCRIPTS / "refresh.ps1"


def load_refresh():
    if not REFRESH_PY.is_file():
        raise AssertionError(f"missing portable refresh orchestrator: {REFRESH_PY}")
    spec = importlib.util.spec_from_file_location("portable_refresh", REFRESH_PY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PortableRefreshTests(unittest.TestCase):
    def test_python_is_single_orchestration_source_and_wrappers_are_thin(self):
        self.assertTrue(REFRESH_PY.is_file())
        self.assertTrue(REFRESH_PS1.is_file())
        shell = REFRESH_SH.read_text(encoding="utf-8")
        powershell = REFRESH_PS1.read_text(encoding="utf-8")
        self.assertIn("refresh.py", shell)
        self.assertIn("refresh.py", powershell)
        for component in ("scrape_snapshot.py", "snapshot_enrich.py", "safe_publish.py"):
            self.assertNotIn(component, shell, "Bash wrapper must not duplicate pipeline logic")
            self.assertNotIn(component, powershell, "PowerShell wrapper must not duplicate pipeline logic")

    def test_environment_parsing_is_platform_neutral_and_preserves_safety_flags(self):
        refresh = load_refresh()
        env = {
            "EDU_RADAR_MIN_ARTICLE_COUNT": "75",
            "EDU_RADAR_MIN_ARTICLE_RATIO": "0.91",
            "EDU_RADAR_ALLOW_SHRINK": "1",
            "EDU_RADAR_VERIFY_OFFICIAL": "0",
            "EDU_RADAR_VERIFY_WORKERS": "4",
            "EDU_RADAR_BASE_URL": "https://example.invalid",
            "EDU_RADAR_KEEP_SNAPSHOTS": "5",
            "EDU_RADAR_REQUEST_TIMEOUT": "12.5",
            "EDU_RADAR_MAX_LIST_PAGES": "44",
            "EDU_RADAR_FETCH_SLEEP": "0",
            "EDU_RADAR_SNAPSHOT_ID": "fixture-snapshot",
        }
        config = refresh.load_config(SKILL_DIR, env)
        self.assertEqual(75, config.min_article_count)
        self.assertAlmostEqual(0.91, config.min_article_ratio)
        self.assertTrue(config.allow_shrink)
        self.assertFalse(config.verify_official)
        self.assertEqual(4, config.verify_workers)
        self.assertEqual("https://example.invalid", config.base_url)
        self.assertEqual(5, config.keep_snapshots)
        self.assertAlmostEqual(12.5, config.request_timeout)
        self.assertEqual(44, config.max_list_pages)
        self.assertEqual(0.0, config.fetch_sleep)
        self.assertEqual("fixture-snapshot", config.snapshot_id)

    def test_staging_directory_is_removed_when_child_process_fails(self):
        refresh = load_refresh()
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skill"
            scripts = skill / "scripts"
            scripts.mkdir(parents=True)
            for name in ("scrape_snapshot.py", "snapshot_enrich.py", "safe_publish.py"):
                (scripts / name).write_text("# fixture\n", encoding="utf-8")
            (skill / "active_snapshot.json").write_text("{}", encoding="utf-8")
            config = refresh.load_config(
                skill,
                {
                    "EDU_RADAR_MIN_ARTICLE_COUNT": "1",
                    "EDU_RADAR_VERIFY_OFFICIAL": "0",
                    "EDU_RADAR_SNAPSHOT_ID": "cleanup-test",
                },
            )
            seen_stage = []

            def failing_runner(command, **kwargs):
                for value in command:
                    if ".refresh-stage." in str(value):
                        seen_stage.append(Path(value))
                raise refresh.RefreshError("synthetic child failure")

            with self.assertRaises(refresh.RefreshError):
                refresh.run_refresh(config, runner=failing_runner)

            self.assertTrue(seen_stage, "test must observe the generated staging directory")
            self.assertTrue(all(not path.exists() for path in seen_stage))

    def test_invalid_boolean_environment_value_is_rejected(self):
        refresh = load_refresh()
        with self.assertRaises(refresh.RefreshError):
            refresh.load_config(SKILL_DIR, {"EDU_RADAR_VERIFY_OFFICIAL": "yes"})


if __name__ == "__main__":
    unittest.main()
