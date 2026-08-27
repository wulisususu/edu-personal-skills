# Install, CI, and FTS Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix installation instructions, establish permanent GitHub Actions CI, and replace catalog-in-context scanning with a snapshot-aware SQLite FTS5 `search.py` query path.

**Architecture:** `catalog.json` remains the canonical, validated catalog-v2 data inside each active immutable snapshot. `search.py` resolves `active_snapshot.json` once, builds a derived SQLite FTS5 index under a gitignored `.search-index/` cache using a temporary file plus `os.replace`, and returns compact JSON search results pointing back to files in the same snapshot. CI validates docs, JSON, Python, shell, catalog-v2 behavior, and FTS search on every push/PR.

**Tech Stack:** Python 3.11/3.12 standard library (`sqlite3`, `argparse`, `json`, `pathlib`), SQLite FTS5, Bash, GitHub Actions, unittest.

**Spec:** User-requested P1/P2 fixes in this conversation.

## Global Constraints

- Preserve `catalog.json` as canonical snapshot data; SQLite is derived/cache only.
- Never mutate immutable `.snapshots/<snapshot_id>` during search.
- Resolve `active_snapshot.json` once per search invocation and keep all results tied to that snapshot.
- Preserve P0 untrusted-data and P1 verification/risk metadata semantics.
- No third-party Python package is required for searching.
- Runtime database/cache files must not be committed.

---

### Task 1: Correct install paths

**Files:**
- Modify: `README.md`
- Test: `tests/test_install_docs.py`

**Interfaces:**
- Consumes: repository layout `skills/dingyi-edu-radar/SKILL.md`.
- Produces: verified `npx skills add wulisususu/edu-personal-skills --skill dingyi-edu-radar` instructions and manual clone+symlink/copy instructions that expose the actual skill directory rather than the repository root.

- [ ] Write tests asserting README uses the current repository and never clones the whole repository directly to `~/.agents/skills/dingyi-edu-radar`.
- [ ] Run the focused test and verify RED against current README.
- [ ] Replace install instructions with current repository + `--skill dingyi-edu-radar`; document clone-to-source then symlink/copy from `skills/dingyi-edu-radar`.
- [ ] Run focused and full tests.

### Task 2: Permanent GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`
- Delete: `.github/workflows/p0-tests.yml`
- Test: `tests/test_ci_contract.py`

**Interfaces:**
- Consumes: all tests and scripts under `tests/` and `skills/dingyi-edu-radar/scripts/`.
- Produces: permanent CI on push and pull request, Python 3.11/3.12 matrix, unittest, JSON parsing, FTS5 capability check, Python compilation, and shell syntax validation.

- [ ] Write tests requiring permanent `ci.yml`, push/PR triggers, Python 3.11+3.12, unittest, FTS5 check, JSON validation, py_compile, and bash syntax validation.
- [ ] Verify RED while only the old P0 workflow exists.
- [ ] Create `ci.yml`, remove old workflow, run CI tests.

### Task 3: SQLite FTS5 search path

**Files:**
- Create: `skills/dingyi-edu-radar/scripts/search.py`
- Modify: `.gitignore`
- Modify: `skills/dingyi-edu-radar/SKILL.md`
- Modify: `README.md`
- Test: `tests/test_search.py`

**Interfaces:**
- Produces CLI: `python3 scripts/search.py QUERY [--category NAME] [--status STATUS] [--max-risk LEVEL] [--limit N] [--rebuild]`.
- Output: JSON object with `snapshot_id`, `query`, `count`, and compact `results[]`; every result contains `slug`, `title`, `file`, `category`, `aliases`, `risk_flags`, `risk_level`, `verification`, `source_url`.
- Derived index path: `<skill>/.search-index/<safe-snapshot-id>.sqlite3`; build to unique temporary sibling then `os.replace`.

- [ ] Write tests for English brand, alias, Chinese partial phrase, category/status/risk filters, punctuation-safe query handling, atomic per-snapshot cache rebuilding, and CLI JSON shape.
- [ ] Verify RED because `search.py` is missing.
- [ ] Implement snapshot resolution, SQLite schema, FTS5 table, CJK n-gram indexing, query sanitization, filtering, ranking, and atomic cache creation using stdlib only.
- [ ] Update SKILL workflow to call `search.py` first rather than loading all catalog JSON into model context; retain catalog fallback only if search execution is unavailable.
- [ ] Gitignore `.search-index/`; update README architecture/usage.
- [ ] Run the entire test suite plus syntax checks and CI.
