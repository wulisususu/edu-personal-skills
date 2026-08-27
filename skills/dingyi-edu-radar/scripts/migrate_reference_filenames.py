#!/usr/bin/env python3
"""One-time/offline migration of catalog reference paths to portable filenames."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path, PurePosixPath

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from reference_paths import reference_filename


class MigrationError(RuntimeError):
    pass


def _load_catalog(skill_dir: Path) -> list[dict]:
    path = skill_dir / "catalog.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot load catalog: {path}: {exc}") from exc
    if not isinstance(value, list):
        raise MigrationError("catalog.json must contain a JSON array")
    if any(not isinstance(item, dict) for item in value):
        raise MigrationError("catalog items must be objects")
    return value


def _safe_existing_reference(skill_dir: Path, file_value: object) -> Path:
    if not isinstance(file_value, str) or not file_value:
        raise MigrationError("catalog file must be a non-empty string")
    rel = PurePosixPath(file_value)
    if rel.is_absolute() or ".." in rel.parts or len(rel.parts) != 2 or rel.parts[0] != "references":
        raise MigrationError(f"unsafe reference path: {file_value!r}")
    path = skill_dir / Path(*rel.parts)
    if path.is_symlink() or not path.is_file():
        raise MigrationError(f"reference file is missing or unsafe: {file_value}")
    return path


def _write_catalog_atomic(path: Path, catalog: list[dict]) -> None:
    tmp = path.parent / f".{path.name}.tmp.{uuid.uuid4().hex}"
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(catalog, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def migrate(skill_dir: Path) -> int:
    skill_dir = Path(skill_dir).resolve()
    catalog = _load_catalog(skill_dir)
    refs_dir = skill_dir / "references"
    if refs_dir.is_symlink() or not refs_dir.is_dir():
        raise MigrationError("references directory is missing or unsafe")

    operations: list[tuple[Path, Path, dict, str]] = []
    target_keys: set[str] = set()

    for index, item in enumerate(catalog):
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            raise MigrationError(f"catalog item {index} has invalid slug")
        old = _safe_existing_reference(skill_dir, item.get("file"))
        new_name = reference_filename(slug)
        new = refs_dir / new_name
        target_key = new_name.casefold()
        if target_key in target_keys:
            raise MigrationError(f"portable filename collision: {new_name}")
        target_keys.add(target_key)
        new_rel = f"references/{new_name}"
        if old != new:
            if new.exists() or new.is_symlink():
                raise MigrationError(f"migration target already exists: {new_rel}")
            operations.append((old, new, item, new_rel))
        else:
            item["file"] = new_rel

    completed: list[tuple[Path, Path]] = []
    try:
        for old, new, item, new_rel in operations:
            old.rename(new)
            completed.append((old, new))
            item["file"] = new_rel
        _write_catalog_atomic(skill_dir / "catalog.json", catalog)
    except Exception:
        for old, new in reversed(completed):
            if new.exists() and not old.exists():
                new.rename(old)
        raise

    return len(operations)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate reference filenames to cross-platform-safe paths.")
    parser.add_argument("--skill-dir", type=Path, default=SCRIPT_DIR.parent)
    args = parser.parse_args()
    try:
        changed = migrate(args.skill_dir)
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"portable reference migration complete: renamed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
