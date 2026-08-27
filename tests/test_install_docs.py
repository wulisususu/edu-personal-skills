from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"


class InstallDocumentationTests(unittest.TestCase):
    def test_npx_install_targets_current_repo_and_specific_skill(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn(
            "npx skills add wulisususu/edu-personal-skills --skill dingyi-edu-radar",
            text,
        )
        self.assertNotIn("npx skills add dingyi/dingyi-edu-radar-skill", text)

    def test_manual_install_exposes_nested_skill_not_repository_root(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn(
            "git clone https://github.com/wulisususu/edu-personal-skills.git ~/.local/share/edu-personal-skills",
            text,
        )
        self.assertIn(
            "~/.local/share/edu-personal-skills/skills/dingyi-edu-radar",
            text,
        )
        self.assertNotIn(
            "git clone https://github.com/dingyi/dingyi-edu-radar-skill.git ~/.agents/skills/dingyi-edu-radar",
            text,
        )
        self.assertIn("SKILL.md", text)


if __name__ == "__main__":
    unittest.main()
