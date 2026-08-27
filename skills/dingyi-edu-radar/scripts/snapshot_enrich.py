#!/usr/bin/env python3
"""Enrich a staged snapshot with catalog-v2 metadata and official verification."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from catalog_metadata import enrich_item, load_registry
from official_verify import verify_item


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


def _load_catalog(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("catalog.json must be a JSON array")
    return data


def enrich_snapshot(
    snapshot_root: Path,
    snapshot_id: str,
    *,
    verify_official: bool,
    workers: int = 8,
) -> dict:
    snapshot_root = snapshot_root.resolve()
    catalog_path = snapshot_root / "catalog.json"
    catalog = _load_catalog(catalog_path)
    registry = load_registry()

    enriched: list[dict] = []
    ref_texts: list[str] = []
    for index, item in enumerate(catalog):
        if not isinstance(item, dict):
            raise ValueError(f"catalog item {index} is not an object")
        rel = item.get("file")
        if not isinstance(rel, str) or not rel.startswith("references/"):
            raise ValueError(f"catalog item {index} has invalid reference path")
        ref = snapshot_root / rel
        text = ref.read_text(encoding="utf-8", errors="replace")
        enriched.append(enrich_item(item, text, registry))
        ref_texts.append(text)

    if verify_official and enriched:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {
                pool.submit(verify_item, item, ref_texts[index], registry=registry): index
                for index, item in enumerate(enriched)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    enriched[index]["verification"] = future.result()
                except Exception:
                    # Official-site availability is advisory; a failure cannot turn a
                    # structurally good snapshot into a partial or destructive refresh.
                    enriched[index]["verification"] = {
                        **_default_verification(),
                        "status": "failed",
                    }
    else:
        for item in enriched:
            item["verification"] = _default_verification()

    catalog_path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    status_counts = Counter(item["verification"]["status"] for item in enriched)
    category_counts = Counter(item["category"] for item in enriched)
    risk_level_counts = Counter(item["risk_level"] for item in enriched)
    risk_flag_counts = Counter(flag for item in enriched for flag in item["risk_flags"])
    generated_at = datetime.now(timezone.utc).isoformat()

    report = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "generated_at": generated_at,
        "verification_mode": "online" if verify_official else "offline",
        "total": len(enriched),
        "status_counts": dict(sorted(status_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "risk_level_counts": dict(sorted(risk_level_counts.items())),
        "risk_flag_counts": dict(sorted(risk_flag_counts.items())),
        # Compatibility summary keys used by lightweight consumers/tests.
        "verified": status_counts.get("verified", 0),
        "candidate": status_counts.get("candidate", 0),
        "needs_review": status_counts.get("needs_review", 0),
        "failed": status_counts.get("failed", 0),
    }
    (snapshot_root / "verification_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    reference_count = len(
        [p for p in (snapshot_root / "references").glob("*.md") if p.is_file() and not p.is_symlink()]
    )
    manifest = {
        "schema_version": 2,
        "snapshot_id": snapshot_id,
        "catalog_count": len(enriched),
        "reference_count": reference_count,
        "generated_at": generated_at,
        "verification_mode": report["verification_mode"],
    }
    (snapshot_root / "snapshot_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"manifest": manifest, "verification_report": report}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--snapshot-id", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-official", action="store_true")
    mode.add_argument("--offline", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 32:
        parser.error("--workers must be between 1 and 32")

    try:
        result = enrich_snapshot(
            args.snapshot_root,
            args.snapshot_id,
            verify_official=args.verify_official and not args.offline,
            workers=args.workers,
        )
    except Exception as exc:
        print(f"ERROR: snapshot enrichment failed: {exc}")
        return 2

    report = result["verification_report"]
    print(
        "snapshot enrichment complete: "
        f"total={report['total']} verified={report['verified']} "
        f"needs_review={report['needs_review']} failed={report['failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
