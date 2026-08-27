# Portable Refresh, Third-Party Notices, and Parser Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make refresh orchestration native on Linux/macOS/Windows, isolate third-party scraped content from the repository MIT license, and add fixture-driven parser/safety regression coverage.

**Architecture:** Move all orchestration from Bash into `refresh.py`; keep `refresh.sh` and add `refresh.ps1` as thin launchers only. `catalog.json` and references remain canonical snapshot data, while generated reference headers and `THIRD_PARTY_NOTICES.md` make copyright provenance explicit. Parser tests use checked-in synthetic HTML fixtures so CI never depends on the live source website.

**Tech Stack:** Python 3.11/3.12 stdlib orchestration, BeautifulSoup/lxml parser, PowerShell, Bash, GitHub Actions, unittest.

**Spec:** Existing P1 snapshot design in `docs/superpowers/specs/2026-08-27-p1-catalog-pipeline-design.md`, extended by this plan.

## Global Constraints

- `refresh.py` is the single source of orchestration truth on every OS.
- Bash/PowerShell wrappers contain no pipeline logic.
- No fixture test makes external network requests.
- Third-party scraped prose is explicitly excluded from the repository MIT grant; software/original project documentation remain under MIT.
- Existing P0 trust-boundary and P1 snapshot/verification/search guarantees must remain green.

---

### Task 1: Portable refresh orchestration

**Files:**
- Create: `skills/dingyi-edu-radar/scripts/refresh.py`
- Modify: `skills/dingyi-edu-radar/scripts/refresh.sh`
- Create: `skills/dingyi-edu-radar/scripts/refresh.ps1`
- Test: `tests/test_portable_refresh.py`

**Interfaces:**
- `refresh.py main(argv: list[str] | None = None) -> int`
- Environment variables remain `EDU_RADAR_*` compatible with the existing shell implementation.
- `--full` remains a compatibility no-op indicating full snapshot mode.

- [ ] Write tests proving the canonical Python orchestrator exists, wrappers delegate only to it, Windows PowerShell is present, environment parsing is platform-neutral, and temporary staging cleanup survives child-process failure.
- [ ] Run tests and confirm RED because `refresh.py` / `refresh.ps1` do not exist and Bash still contains pipeline logic.
- [ ] Implement `refresh.py` using `pathlib`, `tempfile`, `subprocess`, `shutil`, and `datetime`; retain all safety flags and pointer reporting.
- [ ] Replace `refresh.sh` with a thin launcher and add a thin PowerShell launcher.
- [ ] Run the focused tests and full suite.

### Task 2: Third-party copyright isolation

**Files:**
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `skills/dingyi-edu-radar/references/README.md`
- Modify: `README.md`
- Modify: `skills/dingyi-edu-radar/scripts/scrape_snapshot.py`
- Test: `tests/test_third_party_notices.py`

**Interfaces:**
- Every newly generated reference header identifies source provenance and explicitly says the captured third-party content is not covered by the repository MIT license.
- `THIRD_PARTY_NOTICES.md` states no ownership transfer is implied and points users to original sources for rights/terms.

- [ ] Write failing tests for root notice, references notice, README license scope, and generated reference copyright header.
- [ ] Run tests and confirm RED.
- [ ] Add notices and generated provenance header without changing the external-data trust markers.
- [ ] Run focused and full tests.

### Task 3: Parser fixtures, safety, and regressions

**Files:**
- Create: `tests/fixtures/parser/wordpress-article.html`
- Create: `tests/fixtures/parser/fallback-entry-content.html`
- Create: `tests/fixtures/parser/prompt-injection-text.html`
- Create: `tests/fixtures/parser/malformed-no-article.html`
- Create: `tests/test_parser_fixtures.py`
- Modify only if a failing fixture exposes a real parser bug: `skills/dingyi-edu-radar/scripts/scrape_snapshot.py`

**Interfaces:**
- `_parse_article(html, source_url) -> tuple[str, str, str]`
- `build_reference_markdown(...) -> str`

- [ ] Add fixtures for normal WordPress article extraction, fallback `.entry-content`, prompt-injection-like text preserved strictly as data, malformed page rejection, and table/list/link conversion.
- [ ] Run tests and confirm any intended new regression constraints fail before implementation changes.
- [ ] Make minimal parser changes only for demonstrated failures.
- [ ] Run the full test suite.

### Task 4: Cross-platform CI and merge verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

- [ ] Add an OS smoke matrix for `ubuntu-latest`, `macos-latest`, and `windows-latest` on Python 3.12; verify `refresh.py --help`, wrapper presence, parser fixtures, and FTS5.
- [ ] Keep Linux Python 3.11/3.12 full regression jobs.
- [ ] Run the branch CI to completion.
- [ ] Review diff against `main`, create PR, verify PR CI, squash merge, then verify fresh `main` CI.
