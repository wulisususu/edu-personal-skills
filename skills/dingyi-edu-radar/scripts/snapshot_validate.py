#!/usr/bin/env python3
"""Structural validation for immutable edu-radar catalog-v2 snapshots."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


CATEGORIES = {
    "ai", "developer-tools", "design", "productivity", "research", "cloud",
    "media", "shopping", "education-benefit", "edu-mail", "other",
}
RISK_FLAGS = {
    "identity_substitution", "sensitive_identifier", "account_purchase_or_sale",
    "verification_bypass", "bulk_registration", "prompt_injection", "credential_exposure",
}
RISK_LEVELS = {"low", "medium", "high"}
SOURCE_KINDS = {"benefit", "edu_mail"}
VERIFICATION_STATUSES = {"verified", "candidate", "needs_review", "failed"}
VERIFICATION_METHODS = {"configured-domain", "academic-domain", "none"}
REQUIRED_ITEM_FIELDS = {
    "slug", "title", "kw", "file", "source_url", "source_kind", "category",
    "aliases", "risk_flags", "risk_level", "verification", "source_trust",
}
REQUIRED_VERIFICATION_FIELDS = {
    "status", "official_url", "official_domain", "candidate_url", "candidate_domain",
    "verified_at", "http_status", "method",
}


class SnapshotValidationError(RuntimeError):
    pass


def _load_json(path: Path, expected_type):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SnapshotValidationError(f"missing required file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotValidationError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(data, expected_type):
        raise SnapshotValidationError(f"{path.name} has wrong top-level type")
    return data


def _validate_reference_path(snapshot_root: Path, rel: str) -> Path:
    if not isinstance(rel, str):
        raise SnapshotValidationError("catalog file path must be a string")
    posix = PurePosixPath(rel)
    if posix.is_absolute() or ".." in posix.parts:
        raise SnapshotValidationError(f"unsafe reference path: {rel}")
    if len(posix.parts) != 2 or posix.parts[0] != "references" or not posix.name.endswith(".md"):
        raise SnapshotValidationError(f"invalid reference path: {rel}")
    refs_root = (snapshot_root / "references").resolve()
    target = (snapshot_root / Path(*posix.parts)).resolve()
    try:
        target.relative_to(refs_root)
    except ValueError as exc:
        raise SnapshotValidationError(f"reference escapes snapshot: {rel}") from exc
    return target


def _validate_https_url(value: str | None, field: str) -> None:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise SnapshotValidationError(f"{field} must be an https URL")
    parsed = urlparse(value)
    if not parsed.hostname:
        raise SnapshotValidationError(f"{field} has no hostname")


def _validate_verification(verification: object, index: int) -> None:
    if not isinstance(verification, dict):
        raise SnapshotValidationError(f"catalog item {index} verification must be an object")
    missing = REQUIRED_VERIFICATION_FIELDS - set(verification)
    if missing:
        raise SnapshotValidationError(f"catalog item {index} verification missing: {sorted(missing)}")
    status = verification.get("status")
    method = verification.get("method")
    if status not in VERIFICATION_STATUSES:
        raise SnapshotValidationError(f"catalog item {index} invalid verification status: {status}")
    if method not in VERIFICATION_METHODS:
        raise SnapshotValidationError(f"catalog item {index} invalid verification method: {method}")

    if status == "verified":
        official_url = verification.get("official_url")
        official_domain = verification.get("official_domain")
        verified_at = verification.get("verified_at")
        http_status = verification.get("http_status")
        _validate_https_url(official_url, f"catalog item {index} official_url")
        if not isinstance(official_domain, str) or not official_domain.strip():
            raise SnapshotValidationError(f"catalog item {index} verified without official_domain")
        host = (urlparse(official_url).hostname or "").lower()
        domain = official_domain.lower().rstrip(".")
        if host != domain and not host.endswith("." + domain):
            raise SnapshotValidationError(f"catalog item {index} official_domain does not match official_url")
        if not isinstance(verified_at, str) or not verified_at.strip():
            raise SnapshotValidationError(f"catalog item {index} verified without verified_at")
        if not isinstance(http_status, int) or not 200 <= http_status < 400:
            raise SnapshotValidationError(f"catalog item {index} verified without successful http_status")
        if method not in {"configured-domain", "academic-domain"}:
            raise SnapshotValidationError(f"catalog item {index} verified with invalid method")


def _validate_item(snapshot_root: Path, item: object, index: int, seen_slugs: set[str], seen_files: set[str]) -> str:
    if not isinstance(item, dict):
        raise SnapshotValidationError(f"catalog item {index} is not an object")
    missing = REQUIRED_ITEM_FIELDS - set(item)
    if missing:
        raise SnapshotValidationError(f"catalog item {index} missing fields: {sorted(missing)}")

    slug = item.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        raise SnapshotValidationError(f"catalog item {index} invalid slug")
    if slug in seen_slugs:
        raise SnapshotValidationError(f"duplicate slug: {slug}")
    seen_slugs.add(slug)

    for field in ("title", "kw"):
        if not isinstance(item.get(field), str):
            raise SnapshotValidationError(f"catalog item {index} {field} must be a string")
    _validate_https_url(item.get("source_url"), f"catalog item {index} source_url")
    if item.get("source_kind") not in SOURCE_KINDS:
        raise SnapshotValidationError(f"catalog item {index} invalid source_kind")
    if item.get("category") not in CATEGORIES:
        raise SnapshotValidationError(f"catalog item {index} invalid category: {item.get('category')}")
    if item.get("source_trust") != "untrusted":
        raise SnapshotValidationError(f"catalog item {index} source_trust must be untrusted")

    aliases = item.get("aliases")
    if not isinstance(aliases, list) or any(not isinstance(x, str) or not x.strip() for x in aliases):
        raise SnapshotValidationError(f"catalog item {index} aliases must be a string array")
    if len({x.casefold() for x in aliases}) != len(aliases):
        raise SnapshotValidationError(f"catalog item {index} aliases contain duplicates")

    risk_flags = item.get("risk_flags")
    if not isinstance(risk_flags, list) or any(flag not in RISK_FLAGS for flag in risk_flags):
        raise SnapshotValidationError(f"catalog item {index} contains invalid risk_flags")
    if len(set(risk_flags)) != len(risk_flags):
        raise SnapshotValidationError(f"catalog item {index} contains duplicate risk_flags")
    if item.get("risk_level") not in RISK_LEVELS:
        raise SnapshotValidationError(f"catalog item {index} invalid risk_level")

    rel = item.get("file")
    target = _validate_reference_path(snapshot_root, rel)
    if rel in seen_files:
        raise SnapshotValidationError(f"duplicate reference path: {rel}")
    seen_files.add(rel)
    if not target.is_file() or target.is_symlink():
        raise SnapshotValidationError(f"missing or unsafe reference file: {rel}")
    text = target.read_text(encoding="utf-8", errors="replace")
    if "UNTRUSTED_EXTERNAL_DATA" not in text:
        raise SnapshotValidationError(f"reference missing untrusted-data marker: {rel}")

    _validate_verification(item.get("verification"), index)
    return rel


def _validate_counter_mapping(report: dict, key: str, expected: Counter) -> None:
    if key not in report:
        return
    value = report[key]
    if not isinstance(value, dict):
        raise SnapshotValidationError(f"verification_report {key} must be an object")
    normalized: dict[str, int] = {}
    for name, count in value.items():
        if not isinstance(name, str) or not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise SnapshotValidationError(f"verification_report {key} contains invalid counter")
        if count:
            normalized[name] = count
    expected_normalized = {name: count for name, count in expected.items() if count}
    if normalized != expected_normalized:
        raise SnapshotValidationError(f"verification_report {key} does not match catalog")


def _validate_verification_report(report: dict, snapshot_id: str, catalog: list[dict]) -> None:
    if report.get("schema_version") != 1:
        raise SnapshotValidationError("verification_report schema_version must be 1")
    if report.get("snapshot_id") != snapshot_id:
        raise SnapshotValidationError("verification_report snapshot_id mismatch")

    total = report.get("total")
    if total is not None:
        if not isinstance(total, int) or isinstance(total, bool) or total != len(catalog):
            raise SnapshotValidationError("verification_report total mismatch")

    compatibility_keys = ("verified", "candidate", "needs_review", "failed")
    if any(key in report for key in compatibility_keys):
        compat_total = 0
        for key in compatibility_keys:
            value = report.get(key, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SnapshotValidationError(f"verification_report {key} must be a non-negative integer")
            compat_total += value
        if compat_total != len(catalog):
            raise SnapshotValidationError("verification_report compatibility status counts mismatch")

    statuses = Counter(item["verification"]["status"] for item in catalog)
    categories = Counter(item["category"] for item in catalog)
    risk_levels = Counter(item["risk_level"] for item in catalog)
    risk_flags = Counter(flag for item in catalog for flag in item["risk_flags"])
    _validate_counter_mapping(report, "status_counts", statuses)
    _validate_counter_mapping(report, "category_counts", categories)
    _validate_counter_mapping(report, "risk_level_counts", risk_levels)
    _validate_counter_mapping(report, "risk_flag_counts", risk_flags)


def validate_snapshot(
    snapshot_root: Path,
    min_count: int,
    existing_count: int,
    min_ratio: float,
    allow_shrink: bool,
) -> dict:
    snapshot_root = snapshot_root.resolve()
    if min_count < 1:
        raise SnapshotValidationError("min_count must be >= 1")
    if not 0 < min_ratio <= 1:
        raise SnapshotValidationError("min_ratio must be in (0, 1]")

    refs_dir = snapshot_root / "references"
    if not refs_dir.is_dir() or refs_dir.is_symlink():
        raise SnapshotValidationError("missing or unsafe references directory")

    catalog = _load_json(snapshot_root / "catalog.json", list)
    manifest = _load_json(snapshot_root / "snapshot_manifest.json", dict)
    verification_report = _load_json(snapshot_root / "verification_report.json", dict)
    staged_files = sorted(path for path in refs_dir.glob("*.md") if path.is_file() and not path.is_symlink())
    staged_count = len(staged_files)

    if staged_count == 0:
        raise SnapshotValidationError("staged snapshot contains zero references")
    if staged_count < min_count:
        raise SnapshotValidationError(f"staged snapshot too small: {staged_count} < {min_count}")
    if len(catalog) != staged_count:
        raise SnapshotValidationError(f"catalog/reference count mismatch: catalog={len(catalog)} refs={staged_count}")

    if existing_count and not allow_shrink:
        required = max(min_count, math.ceil(existing_count * min_ratio))
        if staged_count < required:
            raise SnapshotValidationError(
                f"unexpected snapshot shrink: existing={existing_count}, staged={staged_count}, required>={required}"
            )

    seen_slugs: set[str] = set()
    seen_files: set[str] = set()
    for index, item in enumerate(catalog):
        _validate_item(snapshot_root, item, index, seen_slugs, seen_files)

    actual_rel = {f"references/{path.name}" for path in staged_files}
    if actual_rel != seen_files:
        missing = sorted(actual_rel ^ seen_files)
        raise SnapshotValidationError(f"catalog/reference file set mismatch: {missing[:5]}")

    if manifest.get("schema_version") != 2:
        raise SnapshotValidationError("snapshot_manifest schema_version must be 2")
    snapshot_id = manifest.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise SnapshotValidationError("snapshot_manifest missing snapshot_id")
    if manifest.get("catalog_count") != len(catalog):
        raise SnapshotValidationError("snapshot_manifest catalog_count mismatch")
    if manifest.get("reference_count") != staged_count:
        raise SnapshotValidationError("snapshot_manifest reference_count mismatch")
    if not isinstance(manifest.get("generated_at"), str) or not manifest.get("generated_at"):
        raise SnapshotValidationError("snapshot_manifest missing generated_at")

    _validate_verification_report(verification_report, snapshot_id, catalog)

    return {
        "schema_version": 2,
        "snapshot_id": snapshot_id,
        "catalog_count": len(catalog),
        "reference_count": staged_count,
        "generated_at": manifest["generated_at"],
    }


if __name__ == "__main__":
    raise SystemExit("snapshot_validate.py is a library used by safe_publish.py")
