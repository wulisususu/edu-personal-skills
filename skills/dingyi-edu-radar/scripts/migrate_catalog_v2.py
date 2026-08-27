#!/usr/bin/env python3
"""Migrate the checked-in bootstrap catalog to catalog-v2 without network claims."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from catalog_metadata import enrich_item, load_registry


SOURCE_RE = re.compile(r"^来源:\s*(https?://\S+)\s*$", re.MULTILINE)
BENEFIT_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def _default_verification() -> dict:
    return {
        "status": "needs_review",
        "official_url": None,
        "official_domain": None,
        "candidate_url": None,
        "candidate_domain": None,
        "verified_at": None,
        "http_status": None,
        "method": "none",
    }


def _legacy_benefit_slugs(skill_dir: Path) -> set[str]:
    path = skill_dir / "CATALOG.md"
    if not path.is_file():
        return set()
    return set(BENEFIT_ROW_RE.findall(path.read_text(encoding="utf-8", errors="replace")))


def _source_url(slug: str, reference_text: str) -> str:
    match = SOURCE_RE.search(reference_text)
    if match:
        return match.group(1).rstrip(".,;，。；")
    return f"https://www.edumails.cn/{slug}.html"


def migrate(skill_dir: Path) -> dict:
    skill_dir = skill_dir.resolve()
    catalog_path = skill_dir / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, list):
        raise ValueError("catalog.json must be an array")

    benefit_slugs = _legacy_benefit_slugs(skill_dir)
    registry = load_registry()
    migrated: list[dict] = []
    for index, item in enumerate(catalog):
        if not isinstance(item, dict):
            raise ValueError(f"catalog item {index} is not an object")
        rel = item.get("file")
        if not isinstance(rel, str):
            raise ValueError(f"catalog item {index} missing file")
        ref_path = skill_dir / rel
        text = ref_path.read_text(encoding="utf-8", errors="replace")
        slug = str(item.get("slug", ""))

        base = dict(item)
        base["source_url"] = base.get("source_url") or _source_url(slug, text)
        if base.get("source_kind") not in {"benefit", "edu_mail"}:
            base["source_kind"] = "benefit" if slug in benefit_slugs else "edu_mail"
        base["source_trust"] = "untrusted"

        enriched = enrich_item(base, text, registry)
        existing_verification = enriched.get("verification")
        if not isinstance(existing_verification, dict) or existing_verification.get("status") not in {
            "verified", "candidate", "needs_review", "failed"
        }:
            enriched["verification"] = _default_verification()
        migrated.append(enriched)

    catalog_path.write_text(json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pointer_path = skill_dir / "active_snapshot.json"
    if pointer_path.is_file():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if isinstance(pointer, dict) and pointer.get("snapshot_id") == "bootstrap":
            pointer["catalog_schema_version"] = 2
            pointer_path.write_text(json.dumps(pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "count": len(migrated),
        "source_kind_counts": dict(Counter(item["source_kind"] for item in migrated)),
        "category_counts": dict(Counter(item["category"] for item in migrated)),
        "risk_level_counts": dict(Counter(item["risk_level"] for item in migrated)),
        "risk_flag_counts": dict(Counter(flag for item in migrated for flag in item["risk_flags"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    args = parser.parse_args()
    try:
        summary = migrate(args.skill_dir)
    except Exception as exc:
        print(f"ERROR: bootstrap catalog migration failed: {exc}")
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
