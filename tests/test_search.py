import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SEARCH_PATH = REPO_ROOT / "skills" / "dingyi-edu-radar" / "scripts" / "search.py"


def load_search_module():
    if not SEARCH_PATH.exists():
        raise AssertionError(f"missing implementation: {SEARCH_PATH}")
    spec = importlib.util.spec_from_file_location("edu_radar_search", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def verification(status="needs_review", official_url=None):
    domain = None
    method = "none"
    http_status = None
    verified_at = None
    if status == "verified":
        domain = official_url.split("/")[2] if official_url else "example.com"
        method = "configured-domain"
        http_status = 200
        verified_at = "2026-08-27T00:00:00+00:00"
    return {
        "status": status,
        "official_url": official_url,
        "official_domain": domain,
        "candidate_url": official_url,
        "candidate_domain": domain,
        "verified_at": verified_at,
        "http_status": http_status,
        "method": method,
    }


def item(slug, title, *, aliases, category, risk_level="low", risk_flags=None, status="needs_review"):
    official = f"https://{slug}.example.com/education" if status == "verified" else None
    return {
        "slug": slug,
        "title": title,
        "kw": title,
        "file": f"references/{slug}.md",
        "source_url": f"https://www.edumails.cn/{slug}.html",
        "source_kind": "benefit",
        "category": category,
        "aliases": aliases,
        "risk_flags": risk_flags or [],
        "risk_level": risk_level,
        "verification": verification(status, official),
        "source_trust": "untrusted",
    }


def write_snapshot(skill: Path, snapshot_id: str, items):
    root = skill / ".snapshots" / snapshot_id
    refs = root / "references"
    refs.mkdir(parents=True, exist_ok=True)
    for entry in items:
        (root / entry["file"]).write_text("<!-- UNTRUSTED_EXTERNAL_DATA -->\n", encoding="utf-8")
    (root / "catalog.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return root


def activate(skill: Path, snapshot_id: str):
    (skill / "active_snapshot.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_id": snapshot_id,
                "snapshot_root": f".snapshots/{snapshot_id}",
                "catalog": "catalog.json",
                "references": "references",
                "catalog_schema_version": 2,
            }
        ),
        encoding="utf-8",
    )


class SQLiteFTSSearchTests(unittest.TestCase):
    def setUp(self):
        self.search_mod = load_search_module()

    def fixture(self, skill: Path, snapshot_id="snap-a"):
        rows = [
            item(
                "chatgpt",
                "ChatGPT Plus Student 教育优惠",
                aliases=["ChatGPT", "OpenAI"],
                category="ai",
                status="verified",
            ),
            item(
                "figma",
                "Figma 在线设计软件学生教育版",
                aliases=["Figma", "可视化设计"],
                category="design",
            ),
            item(
                "northampton",
                "Northampton EDU 邮箱申请",
                aliases=["Northampton", "北安普顿"],
                category="edu-mail",
                risk_level="high",
                risk_flags=["sensitive_identifier"],
            ),
        ]
        write_snapshot(skill, snapshot_id, rows)
        activate(skill, snapshot_id)
        return rows

    def test_brand_alias_and_chinese_partial_search(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skill"
            skill.mkdir()
            self.fixture(skill)

            by_alias = self.search_mod.search(skill, "OpenAI", limit=10)
            by_chinese = self.search_mod.search(skill, "设计", limit=10)

            self.assertEqual("snap-a", by_alias["snapshot_id"])
            self.assertEqual("chatgpt", by_alias["results"][0]["slug"])
            self.assertEqual("figma", by_chinese["results"][0]["slug"])

    def test_category_verification_and_risk_filters(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skill"
            skill.mkdir()
            self.fixture(skill)

            ai = self.search_mod.search(skill, "", category="ai", limit=10)
            verified = self.search_mod.search(skill, "", status="verified", limit=10)
            safe = self.search_mod.search(skill, "", max_risk="medium", limit=10)

            self.assertEqual(["chatgpt"], [x["slug"] for x in ai["results"]])
            self.assertEqual(["chatgpt"], [x["slug"] for x in verified["results"]])
            self.assertNotIn("northampton", [x["slug"] for x in safe["results"]])

    def test_user_query_with_fts_punctuation_is_safe(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skill"
            skill.mkdir()
            self.fixture(skill)

            result = self.search_mod.search(skill, 'ChatGPT (Student) + "???"', limit=10)

            self.assertGreaterEqual(result["count"], 1)
            self.assertEqual("chatgpt", result["results"][0]["slug"])

    def test_index_is_snapshot_scoped_and_rebuilt_after_pointer_switch(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skill"
            skill.mkdir()
            self.fixture(skill, "snap-a")
            first = self.search_mod.search(skill, "OpenAI", limit=10)
            first_index = skill / ".search-index" / "snap-a.sqlite3"
            self.assertTrue(first_index.is_file())
            self.assertEqual("chatgpt", first["results"][0]["slug"])

            write_snapshot(
                skill,
                "snap-b",
                [
                    item(
                        "notion",
                        "Notion 学生教育优惠",
                        aliases=["Notion"],
                        category="productivity",
                    )
                ],
            )
            activate(skill, "snap-b")

            second = self.search_mod.search(skill, "Notion", limit=10)
            second_index = skill / ".search-index" / "snap-b.sqlite3"
            self.assertTrue(second_index.is_file())
            self.assertEqual("snap-b", second["snapshot_id"])
            self.assertEqual(["notion"], [x["slug"] for x in second["results"]])

    def test_cli_outputs_compact_json(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skill"
            skill.mkdir()
            self.fixture(skill)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SEARCH_PATH),
                    "--skill-dir",
                    str(skill),
                    "OpenAI",
                    "--limit",
                    "2",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual("snap-a", payload["snapshot_id"])
            self.assertEqual("OpenAI", payload["query"])
            self.assertEqual(1, payload["count"])
            result = payload["results"][0]
            for key in (
                "slug",
                "title",
                "file",
                "category",
                "aliases",
                "risk_flags",
                "risk_level",
                "verification",
                "source_url",
            ):
                self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
