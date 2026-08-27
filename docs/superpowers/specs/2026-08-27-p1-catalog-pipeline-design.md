# P1 Catalog Pipeline Design

## Goal

Upgrade edu-radar from a scraped article index into a versioned, validated knowledge snapshot with explicit metadata, official-source verification, and an atomic activation boundary.

## Scope

This design implements three P1 requirements:

1. staging + validation + atomic swap;
2. official-source secondary verification;
3. real category / aliases / risk_flags metadata.

The existing `slug/title/kw/file` fields remain for compatibility.

## Architecture

### Immutable snapshots + atomic pointer

The live root `catalog.json` and `references/` remain the bootstrap dataset. A new `active_snapshot.json` points to the currently active dataset. Initially it points to the bootstrap root paths.

Every refresh creates an immutable snapshot under `.snapshots/<snapshot_id>/` containing:

- `catalog.json`
- `references/`
- `snapshot_manifest.json`
- `verification_report.json`

The entire snapshot is validated before publication. Publication first moves/copies the immutable snapshot into `.snapshots/<snapshot_id>/`, then writes a temporary active pointer and switches it with one `os.replace()`. Readers that resolve `active_snapshot.json` once therefore observe one coherent catalog/reference generation. Old snapshots may be garbage-collected only after the pointer switch.

### Catalog v2

Each item retains legacy fields and adds:

```json
{
  "slug": "...",
  "title": "...",
  "kw": "...",
  "file": "references/...md",
  "source_url": "https://www.edumails.cn/...",
  "source_kind": "benefit|edu_mail",
  "category": "ai|developer-tools|design|productivity|research|cloud|media|shopping|education-benefit|edu-mail|other",
  "aliases": ["..."],
  "risk_flags": ["..."],
  "risk_level": "low|medium|high",
  "verification": {
    "status": "verified|candidate|needs_review|failed",
    "official_url": null,
    "official_domain": null,
    "verified_at": null,
    "http_status": null,
    "method": "configured-domain|academic-domain|none"
  },
  "source_trust": "untrusted"
}
```

`category` is a controlled primary category. `aliases` is a deduplicated list used for lookup. `risk_flags` is a controlled list generated from both title and article body.

### Risk flags

Initial controlled flags:

- `identity_substitution`
- `sensitive_identifier`
- `account_purchase_or_sale`
- `verification_bypass`
- `bulk_registration`
- `prompt_injection`
- `credential_exposure`

High-risk flags are not deleted from the dataset, but are explicitly marked so the Agent can ignore unsafe operational guidance. `prompt_injection`, `identity_substitution`, `verification_bypass`, and `bulk_registration` produce `risk_level=high`.

### Official-source verification

Verification is conservative.

- Product articles are verified only when a candidate URL host matches a configured official domain for a recognized product/vendor and the URL returns HTTP 2xx/3xx.
- EDU-mail/institution articles may use an academic-domain candidate (`.edu`, `.edu.*`, `.ac.*`) only when it is linked from the source article and passes HTTP verification.
- Third-party source domains, URL shorteners, generic identity-verification platforms, social networks, and unrelated hosts never become `verified` official sources.
- A plausible but unproven candidate becomes `candidate` or `needs_review`, never `verified`.
- Network failure does not destroy the refresh; it records `failed`/`needs_review` and continues. Structural snapshot validation remains independent of upstream official-site availability.

A maintained `config/official_domains.json` seeds known vendors such as GitHub, Notion, Figma, JetBrains, OpenAI/ChatGPT, Google/Gemini, Adobe, Microsoft, Replit, Perplexity and MATLAB/MathWorks.

## Validation gates

Before activation, validation requires:

- catalog JSON is an array;
- staged reference count equals catalog count;
- unique slug and file path;
- every file path is safe and remains inside the snapshot;
- every item has valid `category`, `aliases`, `risk_flags`, `risk_level`, `verification`, and `source_trust`;
- verified entries contain HTTPS official URL/domain and a successful HTTP status;
- snapshot count satisfies existing minimum-count and shrink-ratio guards;
- manifest counts match the actual snapshot;
- no partial parse errors.

## Agent consumption

`SKILL.md` must read `active_snapshot.json` first. It then reads the pointed catalog and resolves each catalog `file` relative to the pointed snapshot root. If the pointer is absent, it falls back to the root bootstrap catalog/references for backward compatibility.

The Agent uses `category` for reverse queries, `aliases` for matching, `risk_flags` to avoid unsafe operational details, and `verification.status/official_url` to distinguish confirmed official information from third-party claims.

## Error handling

- Fetch/parse failure: staged snapshot rejected; active pointer unchanged.
- Schema/quality failure: staged snapshot rejected; active pointer unchanged.
- Official-site verification failure: item downgraded to `needs_review`/`failed`; snapshot may still publish.
- Pointer activation failure: old pointer remains active.

## Testing

Tests cover metadata classification/aliases/risk detection, conservative official verification with a local HTTP fixture, catalog schema validation, snapshot manifest integrity, failed validation preserving the active pointer, and successful publish atomically switching the pointer to a new immutable snapshot.