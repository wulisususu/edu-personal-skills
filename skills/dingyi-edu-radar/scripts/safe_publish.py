#!/usr/bin/env python3
"""Validate and publish a refreshed edu-radar snapshot without risking live data."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import uuid
from pathlib import Path


class SnapshotValidationError(RuntimeError):
    pass


def _load_catalog(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SnapshotValidationError(f"missing catalog: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotValidationError(f"invalid catalog JSON: {path}: {exc}") from exc
    if not isinstance(data, list):
        raise SnapshotValidationError("catalog.json must contain a JSON array")
    return data


def _count_existing(skill_dir: Path) -> int:
    refs = skill_dir / "references"
    ref_count = len(list(refs.glob("*.md"))) if refs.exists() else 0
    catalog_path = skill_dir / "catalog.json"
    catalog_count = 0
    if catalog_path.exists():
        try:
            catalog_count = len(_load_catalog(catalog_path))
        except SnapshotValidationError:
            # A damaged catalog must not weaken the shrink guard. Existing files still count.
            catalog_count = 0
    return max(ref_count, catalog_count)


def validate_snapshot(
    skill_dir: Path,
    stage_dir: Path,
    min_count: int,
    min_ratio: float,
    allow_shrink: bool,
) -> tuple[int, int]:
    refs = stage_dir / "references"
    catalog_path = stage_dir / "catalog.json"
    if not refs.is_dir():
        raise SnapshotValidationError(f"missing staged references directory: {refs}")

    staged_files = sorted(refs.glob("*.md"))
    staged_count = len(staged_files)
    if staged_count == 0:
        raise SnapshotValidationError("staged snapshot contains zero references")
    if staged_count < min_count:
        raise SnapshotValidationError(
            f"staged snapshot too small: {staged_count} < minimum {min_count}"
        )

    catalog = _load_catalog(catalog_path)
    if len(catalog) != staged_count:
        raise SnapshotValidationError(
            f"catalog/reference count mismatch: catalog={len(catalog)} refs={staged_count}"
        )

    seen_files: set[str] = set()
    for index, item in enumerate(catalog):
        if not isinstance(item, dict):
            raise SnapshotValidationError(f"catalog item {index} is not an object")
        rel = item.get("file")
        if not isinstance(rel, str) or not rel.startswith("references/"):
            raise SnapshotValidationError(f"catalog item {index} has invalid file path: {rel!r}")
        if rel in seen_files:
            raise SnapshotValidationError(f"duplicate catalog file path: {rel}")
        seen_files.add(rel)
        target = stage_dir / rel
        if not target.is_file():
            raise SnapshotValidationError(f"catalog points to missing staged file: {rel}")

    existing_count = _count_existing(skill_dir)
    if existing_count and not allow_shrink:
        required = max(min_count, math.ceil(existing_count * min_ratio))
        if staged_count < required:
            raise SnapshotValidationError(
                "unexpected snapshot shrink: "
                f"existing={existing_count}, staged={staged_count}, required>={required}; "
                "live data left untouched"
            )

    return existing_count, staged_count


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def publish_snapshot(skill_dir: Path, stage_dir: Path) -> None:
    live_refs = skill_dir / "references"
    live_catalog = skill_dir / "catalog.json"
    staged_refs = stage_dir / "references"
    staged_catalog = stage_dir / "catalog.json"

    backup_root = skill_dir / f".refresh-backup-{uuid.uuid4().hex}"
    backup_root.mkdir(parents=False, exist_ok=False)
    backup_refs = backup_root / "references"
    backup_catalog = backup_root / "catalog.json"

    refs_backed_up = False
    catalog_backed_up = False
    refs_installed = False
    catalog_installed = False

    try:
        if live_refs.exists():
            os.replace(live_refs, backup_refs)
            refs_backed_up = True
        os.replace(staged_refs, live_refs)
        refs_installed = True

        if live_catalog.exists():
            os.replace(live_catalog, backup_catalog)
            catalog_backed_up = True
        os.replace(staged_catalog, live_catalog)
        catalog_installed = True
    except Exception:
        # Best-effort rollback. Never delete backups until both live paths are installed.
        if catalog_installed:
            _remove_path(live_catalog)
        if catalog_backed_up and backup_catalog.exists():
            os.replace(backup_catalog, live_catalog)

        if refs_installed:
            _remove_path(live_refs)
        if refs_backed_up and backup_refs.exists():
            os.replace(backup_refs, live_refs)
        raise
    else:
        shutil.rmtree(backup_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", required=True, type=Path)
    parser.add_argument("--stage-dir", required=True, type=Path)
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--min-ratio", type=float, default=0.8)
    parser.add_argument("--allow-shrink", action="store_true")
    args = parser.parse_args()

    if args.min_count < 1:
        parser.error("--min-count must be >= 1")
    if not 0 < args.min_ratio <= 1:
        parser.error("--min-ratio must be in (0, 1]")

    skill_dir = args.skill_dir.resolve()
    stage_dir = args.stage_dir.resolve()

    try:
        existing_count, staged_count = validate_snapshot(
            skill_dir,
            stage_dir,
            args.min_count,
            args.min_ratio,
            args.allow_shrink,
        )
        publish_snapshot(skill_dir, stage_dir)
    except SnapshotValidationError as exc:
        print(f"ERROR: refresh snapshot rejected: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: failed to publish refresh snapshot: {exc}", file=sys.stderr)
        return 3

    print(
        f"safe publish complete: existing={existing_count}, staged={staged_count}, "
        f"live={staged_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
