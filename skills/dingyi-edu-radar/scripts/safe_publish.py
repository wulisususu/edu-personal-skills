#!/usr/bin/env python3
"""Validate, install, and atomically activate an immutable edu-radar snapshot."""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from snapshot_validate import SnapshotValidationError, validate_snapshot


SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ACTIVE_POINTER = "active_snapshot.json"
SNAPSHOTS_DIR = ".snapshots"


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_relative_dir(value: object) -> PurePosixPath | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def _count_root_bootstrap(skill_dir: Path) -> int:
    refs = skill_dir / "references"
    refs_count = len([p for p in refs.glob("*.md") if p.is_file()]) if refs.is_dir() else 0
    catalog_count = 0
    try:
        catalog = _load_json(skill_dir / "catalog.json")
        if isinstance(catalog, list):
            catalog_count = len(catalog)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return max(refs_count, catalog_count)


def _count_active_snapshot(skill_dir: Path) -> int:
    pointer_path = skill_dir / ACTIVE_POINTER
    if not pointer_path.is_file():
        return _count_root_bootstrap(skill_dir)
    try:
        pointer = _load_json(pointer_path)
    except (OSError, ValueError, json.JSONDecodeError):
        # A malformed pointer must never weaken the shrink guard.
        return _count_root_bootstrap(skill_dir)
    if not isinstance(pointer, dict):
        return _count_root_bootstrap(skill_dir)

    root_rel = _safe_relative_dir(pointer.get("snapshot_root"))
    refs_rel = _safe_relative_dir(pointer.get("references"))
    if root_rel is None or refs_rel is None:
        return _count_root_bootstrap(skill_dir)

    snapshot_root = (skill_dir / Path(*root_rel.parts)).resolve()
    refs = (snapshot_root / Path(*refs_rel.parts)).resolve()
    try:
        refs.relative_to(snapshot_root)
        snapshot_root.relative_to(skill_dir.resolve())
    except ValueError:
        return _count_root_bootstrap(skill_dir)
    if not refs.is_dir() or refs.is_symlink():
        return _count_root_bootstrap(skill_dir)
    return len([p for p in refs.glob("*.md") if p.is_file() and not p.is_symlink()])


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.parent / f".{path.name}.tmp.{uuid.uuid4().hex}"
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        # Persist the directory entry when the platform supports directory fsync.
        try:
            fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            fd = None
        if fd is not None:
            try:
                os.fsync(fd)
            except OSError:
                pass
            finally:
                os.close(fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def _install_snapshot(stage_dir: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"snapshot destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(stage_dir, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # Cross-filesystem fallback: copy to a hidden sibling, then rename within the
        # destination filesystem so the visible immutable snapshot appears atomically.
        incoming = destination.parent / f".incoming-{destination.name}-{uuid.uuid4().hex}"
        try:
            shutil.copytree(stage_dir, incoming, symlinks=False)
            os.replace(incoming, destination)
        finally:
            if incoming.exists():
                shutil.rmtree(incoming)


def _garbage_collect_snapshots(skill_dir: Path, active_id: str, keep_snapshots: int) -> None:
    if keep_snapshots < 1:
        return
    root = skill_dir / SNAPSHOTS_DIR
    if not root.is_dir():
        return
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and path.name != active_id
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    # `keep_snapshots` includes the active snapshot, so keep N-1 historical snapshots.
    keep_history = max(0, keep_snapshots - 1)
    for stale in candidates[keep_history:]:
        shutil.rmtree(stale)


def publish_snapshot(
    skill_dir: Path,
    stage_dir: Path,
    summary: dict,
    *,
    keep_snapshots: int = 3,
) -> dict:
    snapshot_id = str(summary.get("snapshot_id", ""))
    if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise SnapshotValidationError(f"unsafe snapshot_id: {snapshot_id!r}")

    snapshots_root = skill_dir / SNAPSHOTS_DIR
    destination = snapshots_root / snapshot_id
    _install_snapshot(stage_dir, destination)

    pointer = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "snapshot_root": f"{SNAPSHOTS_DIR}/{snapshot_id}",
        "catalog": "catalog.json",
        "references": "references",
        "manifest": "snapshot_manifest.json",
        "verification_report": "verification_report.json",
        "activated_at": datetime.now(timezone.utc).isoformat(),
        "catalog_schema_version": int(summary.get("schema_version", 2)),
    }

    pointer_path = skill_dir / ACTIVE_POINTER
    try:
        _atomic_write_json(pointer_path, pointer)
    except Exception:
        # The pointer is the commit point. If it did not switch, remove the newly
        # installed snapshot and preserve the previously active generation.
        if destination.exists():
            shutil.rmtree(destination)
        raise

    try:
        _garbage_collect_snapshots(skill_dir, snapshot_id, keep_snapshots)
    except Exception as exc:
        # GC is post-commit maintenance and must never invalidate a successful switch.
        print(f"WARNING: snapshot GC failed after activation: {exc}", file=sys.stderr)
    return pointer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", required=True, type=Path)
    parser.add_argument("--stage-dir", required=True, type=Path)
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--min-ratio", type=float, default=0.8)
    parser.add_argument("--allow-shrink", action="store_true")
    parser.add_argument("--keep-snapshots", type=int, default=3)
    args = parser.parse_args()

    if args.min_count < 1:
        parser.error("--min-count must be >= 1")
    if not 0 < args.min_ratio <= 1:
        parser.error("--min-ratio must be in (0, 1]")
    if args.keep_snapshots < 1:
        parser.error("--keep-snapshots must be >= 1")

    skill_dir = args.skill_dir.resolve()
    stage_dir = args.stage_dir.resolve()
    if not skill_dir.is_dir():
        print(f"ERROR: skill directory does not exist: {skill_dir}", file=sys.stderr)
        return 2
    if not stage_dir.is_dir():
        print(f"ERROR: stage directory does not exist: {stage_dir}", file=sys.stderr)
        return 2

    existing_count = _count_active_snapshot(skill_dir)
    try:
        summary = validate_snapshot(
            stage_dir,
            args.min_count,
            existing_count,
            args.min_ratio,
            args.allow_shrink,
        )
        pointer = publish_snapshot(
            skill_dir,
            stage_dir,
            summary,
            keep_snapshots=args.keep_snapshots,
        )
    except SnapshotValidationError as exc:
        print(f"ERROR: refresh snapshot rejected: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: failed to publish refresh snapshot: {exc}", file=sys.stderr)
        return 3

    print(
        "safe publish complete: "
        f"existing={existing_count}, staged={summary['reference_count']}, "
        f"active={pointer['snapshot_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
