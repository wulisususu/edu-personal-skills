# P1 Catalog Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build versioned validated snapshots, conservative official-source verification, and structured category/aliases/risk metadata without breaking the existing bootstrap dataset.

**Architecture:** Refresh builds an immutable staged snapshot, enriches every catalog item, validates cross-file invariants, installs the snapshot under `.snapshots/<id>`, then atomically replaces `active_snapshot.json`. `SKILL.md` resolves the active pointer once and consumes one coherent generation.

**Tech Stack:** Python 3.12 stdlib, Bash, BeautifulSoup/lxml already used by refresh, unittest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-27-p1-catalog-pipeline-design.md`

## Global Constraints

- Preserve legacy `slug/title/kw/file` fields.
- Do not add a mandatory third-party Python dependency for validation or verification.
- Never mark an official source `verified` from fuzzy text similarity alone.
- Official-site network failure must not invalidate an otherwise structurally valid snapshot.
- Failed staging/schema/quality validation must leave `active_snapshot.json` unchanged.
- Snapshot activation must be a single atomic `os.replace()` of the active pointer.

---

### Task 1: Structured metadata enrichment

**Files:**
- Create: `skills/dingyi-edu-radar/scripts/catalog_metadata.py`
- Create: `skills/dingyi-edu-radar/config/official_domains.json`
- Test: `tests/test_p1_catalog_pipeline.py`

**Interfaces:**
- Produces `enrich_item(item: dict, reference_text: str) -> dict`.
- Produces controlled `category`, `aliases`, `risk_flags`, `risk_level`.

- [ ] Write failing tests for AI/developer/design/edu-mail categories, alias normalization, and all controlled risk flags.
- [ ] Run `python -m unittest tests.test_p1_catalog_pipeline -v` and confirm failures are caused by missing enrichment code.
- [ ] Implement deterministic enrichment using controlled keyword rules plus a small known-alias map.
- [ ] Re-run the tests and keep legacy fields unchanged.

### Task 2: Conservative official-source verifier

**Files:**
- Create: `skills/dingyi-edu-radar/scripts/official_verify.py`
- Modify: `skills/dingyi-edu-radar/config/official_domains.json`
- Test: `tests/test_p1_catalog_pipeline.py`

**Interfaces:**
- Consumes enriched catalog item and reference Markdown.
- Produces `verification` object with `verified|candidate|needs_review|failed`.

- [ ] Write failing tests using a local HTTP server and configured fake domain/URL override to prove 2xx/3xx configured candidates verify, unrelated candidates do not, and network failure downgrades without throwing.
- [ ] Implement URL extraction, candidate filtering, host matching, and timeout-bounded HTTP verification using stdlib `urllib`.
- [ ] Add academic-domain recognition for EDU-mail entries without treating generic third-party/student-verification hosts as official.
- [ ] Re-run tests.

### Task 3: Snapshot schema and validation

**Files:**
- Create: `skills/dingyi-edu-radar/scripts/snapshot_validate.py`
- Create: `skills/dingyi-edu-radar/schemas/catalog-v2.schema.json`
- Test: `tests/test_p1_catalog_pipeline.py`

**Interfaces:**
- Produces `validate_snapshot(snapshot_root: Path, min_count: int, existing_count: int, min_ratio: float, allow_shrink: bool) -> dict`.
- Returns a manifest summary and raises `SnapshotValidationError` on structural failure.

- [ ] Write failing tests for invalid category, invalid risk flag, path traversal, duplicate slug, verified entry without official evidence, manifest mismatch, and valid v2 snapshot.
- [ ] Implement stdlib validation mirroring the checked-in JSON schema.
- [ ] Ensure verification network state is not a structural failure unless an entry claims `verified` without evidence.
- [ ] Re-run tests.

### Task 4: Atomic snapshot activation

**Files:**
- Rewrite: `skills/dingyi-edu-radar/scripts/safe_publish.py`
- Create: `skills/dingyi-edu-radar/active_snapshot.json`
- Modify: `tests/test_p0_guards.py`
- Test: `tests/test_p1_catalog_pipeline.py`

**Interfaces:**
- `safe_publish.py` installs immutable `.snapshots/<snapshot_id>/` then atomically replaces `active_snapshot.json`.
- Active pointer contains `snapshot_id`, `snapshot_root`, `catalog`, `references`, `activated_at`, `schema_version`.

- [ ] Write failing tests proving failed validation leaves bootstrap pointer untouched and successful publish switches one pointer while old data remains available.
- [ ] Preserve bootstrap fallback semantics for existing root catalog/references.
- [ ] Implement immutable snapshot install and temp-file + `os.replace()` pointer activation.
- [ ] Add bounded snapshot garbage collection that never deletes bootstrap or the active snapshot.
- [ ] Re-run P0 and P1 tests.

### Task 5: Wire enrichment/verification/validation into refresh

**Files:**
- Modify: `skills/dingyi-edu-radar/scripts/refresh.sh`
- Modify: `skills/dingyi-edu-radar/SKILL.md`
- Modify: `.gitignore`
- Modify: `.github/workflows/p0-tests.yml`
- Test: `tests/test_p1_catalog_pipeline.py`

**Interfaces:**
- Refresh parser emits source URLs and source kind.
- Metadata enrichment and official verification run before structural validation and safe publish.

- [ ] Write failing static-wiring tests for required pipeline steps and active-pointer consumption instructions.
- [ ] Update refresh parser to preserve outbound URLs/source kind and emit catalog v2 base data.
- [ ] Run metadata enrichment and official verification on staged catalog/references.
- [ ] Generate `snapshot_manifest.json` and `verification_report.json`.
- [ ] Validate staged snapshot, then call safe publisher.
- [ ] Update `SKILL.md` to use active pointer and verification/risk/category semantics.
- [ ] Ignore runtime `.snapshots/` and temporary pointer files.
- [ ] Extend CI to py_compile all new Python modules plus `bash -n`.
- [ ] Run the full suite and syntax checks.

### Task 6: Migrate the checked-in bootstrap catalog to v2 metadata

**Files:**
- Create: `skills/dingyi-edu-radar/scripts/migrate_catalog_v2.py`
- Modify: `skills/dingyi-edu-radar/catalog.json`
- Test: `tests/test_p1_catalog_pipeline.py`

**Interfaces:**
- Offline migration enriches current catalog from checked-in references without claiming online official verification.

- [ ] Write a failing repository-level test asserting every bootstrap catalog item contains valid v2 metadata.
- [ ] Implement deterministic offline migration with verification status `candidate|needs_review` unless an existing trusted verification record is present.
- [ ] Run migration once against the branch catalog.
- [ ] Validate the migrated bootstrap catalog and run all tests.

### Task 7: Final review and merge

- [ ] Compare branch to `main` and verify changes are scoped to the three P1 requirements plus tests/docs.
- [ ] Run GitHub Actions on the final head and require green regression, Python syntax, and Bash syntax checks.
- [ ] Open a PR describing schema compatibility, atomic pointer semantics, official verification guarantees, and bootstrap migration.
- [ ] Merge only after PR checks pass, then verify the post-merge `main` workflow is green.