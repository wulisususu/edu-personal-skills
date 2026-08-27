#!/usr/bin/env python3
"""Snapshot-aware SQLite FTS5 search for edu-radar catalog v2.

`catalog.json` remains canonical. This script builds a disposable, snapshot-scoped
SQLite index outside immutable snapshot directories and returns compact JSON
candidates for the Agent to inspect further.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


ACTIVE_POINTER = "active_snapshot.json"
CACHE_DIR = ".search-index"
SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
CJK_SEQUENCE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
RISK_RANK = {"low": 0, "medium": 1, "high": 2}
VERIFICATION_STATUSES = {"verified", "candidate", "needs_review", "failed"}


class SearchError(RuntimeError):
    pass


def _load_json(path: Path, expected_type: type) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SearchError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SearchError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, expected_type):
        raise SearchError(f"wrong JSON type in {path}")
    return value


def _safe_relative(value: object, *, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise SearchError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise SearchError(f"unsafe {field}: {value}")
    return path


def resolve_snapshot(skill_dir: Path) -> dict[str, Any]:
    """Resolve exactly one active snapshot for a search invocation."""
    skill_dir = skill_dir.resolve()
    pointer_path = skill_dir / ACTIVE_POINTER
    if pointer_path.exists():
        if pointer_path.is_symlink() or not pointer_path.is_file():
            raise SearchError("active_snapshot.json must be a regular file")
        pointer = _load_json(pointer_path, dict)
        snapshot_id = pointer.get("snapshot_id")
        root_rel = _safe_relative(pointer.get("snapshot_root"), field="snapshot_root")
        catalog_rel = _safe_relative(pointer.get("catalog", "catalog.json"), field="catalog")
    else:
        pointer = {}
        snapshot_id = "bootstrap"
        root_rel = PurePosixPath(".")
        catalog_rel = PurePosixPath("catalog.json")

    if not isinstance(snapshot_id, str) or not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise SearchError(f"unsafe snapshot_id: {snapshot_id!r}")

    unresolved_root = skill_dir / Path(*root_rel.parts)
    if unresolved_root.is_symlink():
        raise SearchError("snapshot_root must not be a symlink")
    snapshot_root = unresolved_root.resolve()
    try:
        snapshot_root.relative_to(skill_dir)
    except ValueError as exc:
        raise SearchError("snapshot_root escapes skill directory") from exc
    if not snapshot_root.is_dir():
        raise SearchError(f"snapshot_root is not a directory: {snapshot_root}")

    catalog_path = (snapshot_root / Path(*catalog_rel.parts)).resolve()
    try:
        catalog_path.relative_to(snapshot_root)
    except ValueError as exc:
        raise SearchError("catalog path escapes snapshot") from exc
    if catalog_path.is_symlink() or not catalog_path.is_file():
        raise SearchError(f"catalog is missing or unsafe: {catalog_path}")

    root_display = "." if root_rel == PurePosixPath(".") else root_rel.as_posix()
    return {
        "snapshot_id": snapshot_id,
        "snapshot_root": snapshot_root,
        "snapshot_root_rel": root_display,
        "catalog_path": catalog_path,
        "pointer": pointer,
    }


def _catalog_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cjk_ngrams(sequence: str) -> list[str]:
    if len(sequence) == 1:
        return [sequence]
    terms: list[str] = []
    for size in (2, 3):
        if len(sequence) < size:
            continue
        terms.extend(sequence[index : index + size] for index in range(len(sequence) - size + 1))
    return terms


def _tokenize_for_fts(text: str) -> list[str]:
    """Produce portable FTS tokens, including CJK n-grams for short queries."""
    terms: list[str] = []
    terms.extend(match.group(0).casefold() for match in ASCII_TOKEN_RE.finditer(text))
    for match in CJK_SEQUENCE_RE.finditer(text):
        terms.extend(_cjk_ngrams(match.group(0)))
    # Stable de-duplication keeps indexes compact and query expressions deterministic.
    return list(dict.fromkeys(term for term in terms if term))


def _fts_expression(query: str) -> str | None:
    terms = _tokenize_for_fts(query)
    if not terms:
        return None
    # Terms come only from controlled regexes, but quoting still prevents FTS operators
    # from being interpreted if tokenization rules change later.
    return " AND ".join(f'"{term.replace(chr(34), "")}"' for term in terms)


def _prepare_cache_root(skill_dir: Path) -> Path:
    root = skill_dir / CACHE_DIR
    if root.is_symlink():
        raise SearchError(f"search cache must not be a symlink: {root}")
    if root.exists():
        if not root.is_dir():
            raise SearchError(f"search cache is not a directory: {root}")
    else:
        root.mkdir(mode=0o700)
    resolved = root.resolve()
    try:
        resolved.relative_to(skill_dir.resolve())
    except ValueError as exc:
        raise SearchError("search cache escapes skill directory") from exc
    return root


def index_path_for_snapshot(skill_dir: Path, snapshot_id: str) -> Path:
    if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise SearchError(f"unsafe snapshot_id: {snapshot_id!r}")
    return skill_dir.resolve() / CACHE_DIR / f"{snapshot_id}.sqlite3"


def _index_matches(path: Path, snapshot_id: str, catalog_sha256: str) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = dict(connection.execute("SELECT key, value FROM meta").fetchall())
            return (
                rows.get("schema_version") == "1"
                and rows.get("snapshot_id") == snapshot_id
                and rows.get("catalog_sha256") == catalog_sha256
            )
        finally:
            connection.close()
    except (sqlite3.Error, OSError, ValueError):
        return False


def _validate_catalog_item(item: object, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise SearchError(f"catalog item {index} is not an object")
    required = (
        "slug",
        "title",
        "kw",
        "file",
        "source_url",
        "category",
        "aliases",
        "risk_flags",
        "risk_level",
        "verification",
    )
    missing = [field for field in required if field not in item]
    if missing:
        raise SearchError(f"catalog item {index} missing fields: {missing}")
    if not isinstance(item["aliases"], list) or any(not isinstance(x, str) for x in item["aliases"]):
        raise SearchError(f"catalog item {index} has invalid aliases")
    if not isinstance(item["risk_flags"], list) or any(not isinstance(x, str) for x in item["risk_flags"]):
        raise SearchError(f"catalog item {index} has invalid risk_flags")
    if item["risk_level"] not in RISK_RANK:
        raise SearchError(f"catalog item {index} has invalid risk_level")
    verification = item["verification"]
    if not isinstance(verification, dict) or verification.get("status") not in VERIFICATION_STATUSES:
        raise SearchError(f"catalog item {index} has invalid verification")
    return item


def _build_index(index_path: Path, catalog_path: Path, snapshot_id: str, catalog_sha256: str) -> None:
    catalog = _load_json(catalog_path, list)
    cache_root = index_path.parent
    temp_path = cache_root / f".{snapshot_id}.{uuid.uuid4().hex}.sqlite3"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temp_path)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            """
            CREATE TABLE docs (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                kw TEXT NOT NULL,
                file TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                category TEXT NOT NULL,
                aliases_json TEXT NOT NULL,
                risk_flags_json TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                risk_rank INTEGER NOT NULL,
                verification_status TEXT NOT NULL,
                verification_json TEXT NOT NULL
            )
            """
        )
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE docs_fts USING fts5(search_text, tokenize='unicode61 remove_diacritics 2')"
            )
        except sqlite3.OperationalError as exc:
            raise SearchError("SQLite FTS5 is not available in this Python runtime") from exc

        connection.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            (
                ("schema_version", "1"),
                ("snapshot_id", snapshot_id),
                ("catalog_sha256", catalog_sha256),
            ),
        )

        for rowid, raw_item in enumerate(catalog, start=1):
            item = _validate_catalog_item(raw_item, rowid - 1)
            aliases = item["aliases"]
            risk_flags = item["risk_flags"]
            verification = item["verification"]
            source_kind = str(item.get("source_kind", ""))
            searchable = " ".join(
                [
                    str(item["slug"]),
                    str(item["title"]),
                    str(item["kw"]),
                    " ".join(aliases),
                    str(item["category"]),
                    source_kind,
                ]
            )
            search_text = " ".join(_tokenize_for_fts(searchable))
            connection.execute(
                """
                INSERT INTO docs(
                    id, slug, title, kw, file, source_url, source_kind, category,
                    aliases_json, risk_flags_json, risk_level, risk_rank,
                    verification_status, verification_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rowid,
                    str(item["slug"]),
                    str(item["title"]),
                    str(item["kw"]),
                    str(item["file"]),
                    str(item["source_url"]),
                    source_kind,
                    str(item["category"]),
                    json.dumps(aliases, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(risk_flags, ensure_ascii=False, separators=(",", ":")),
                    str(item["risk_level"]),
                    RISK_RANK[str(item["risk_level"])],
                    str(verification["status"]),
                    json.dumps(verification, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            connection.execute(
                "INSERT INTO docs_fts(rowid, search_text) VALUES (?, ?)",
                (rowid, search_text),
            )

        connection.commit()
        connection.close()
        connection = None

        fd = os.open(temp_path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp_path, index_path)
        try:
            dir_fd = os.open(cache_root, os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            finally:
                os.close(dir_fd)
    finally:
        if connection is not None:
            connection.close()
        if temp_path.exists():
            temp_path.unlink()


def ensure_index(skill_dir: Path, snapshot: dict[str, Any], *, rebuild: bool = False) -> Path:
    cache_root = _prepare_cache_root(skill_dir.resolve())
    index_path = cache_root / f"{snapshot['snapshot_id']}.sqlite3"
    catalog_sha256 = _catalog_sha256(snapshot["catalog_path"])
    if rebuild or not _index_matches(index_path, snapshot["snapshot_id"], catalog_sha256):
        _build_index(index_path, snapshot["catalog_path"], snapshot["snapshot_id"], catalog_sha256)
    return index_path


def _result_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "slug": row["slug"],
        "title": row["title"],
        "file": row["file"],
        "category": row["category"],
        "aliases": json.loads(row["aliases_json"]),
        "risk_flags": json.loads(row["risk_flags_json"]),
        "risk_level": row["risk_level"],
        "verification": json.loads(row["verification_json"]),
        "source_url": row["source_url"],
    }


def search(
    skill_dir: Path,
    query: str,
    *,
    category: str | None = None,
    status: str | None = None,
    max_risk: str = "high",
    limit: int = 10,
    rebuild: bool = False,
) -> dict[str, Any]:
    if max_risk not in RISK_RANK:
        raise SearchError(f"invalid max_risk: {max_risk}")
    if status is not None and status not in VERIFICATION_STATUSES:
        raise SearchError(f"invalid verification status: {status}")
    if not 1 <= limit <= 100:
        raise SearchError("limit must be between 1 and 100")

    skill_dir = Path(skill_dir).resolve()
    snapshot = resolve_snapshot(skill_dir)
    index_path = ensure_index(skill_dir, snapshot, rebuild=rebuild)
    expression = _fts_expression(query)

    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    try:
        params: list[Any] = []
        where: list[str] = []
        if category is not None:
            where.append("d.category = ?")
            params.append(category)
        if status is not None:
            where.append("d.verification_status = ?")
            params.append(status)
        where.append("d.risk_rank <= ?")
        params.append(RISK_RANK[max_risk])

        if expression:
            sql = (
                "SELECT d.*, bm25(docs_fts) AS fts_rank "
                "FROM docs_fts JOIN docs d ON d.id = docs_fts.rowid "
                "WHERE docs_fts MATCH ?"
            )
            query_params: list[Any] = [expression]
            if where:
                sql += " AND " + " AND ".join(where)
            sql += (
                " ORDER BY CASE d.verification_status WHEN 'verified' THEN 0 WHEN 'candidate' THEN 1 "
                "WHEN 'needs_review' THEN 2 ELSE 3 END, fts_rank ASC, d.risk_rank ASC, d.title COLLATE NOCASE ASC LIMIT ?"
            )
            query_params.extend(params)
            query_params.append(limit)
        else:
            sql = "SELECT d.* FROM docs d"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += (
                " ORDER BY CASE d.verification_status WHEN 'verified' THEN 0 WHEN 'candidate' THEN 1 "
                "WHEN 'needs_review' THEN 2 ELSE 3 END, d.risk_rank ASC, d.title COLLATE NOCASE ASC LIMIT ?"
            )
            query_params = [*params, limit]

        rows = connection.execute(sql, query_params).fetchall()
    except sqlite3.Error as exc:
        raise SearchError(f"SQLite search failed: {exc}") from exc
    finally:
        connection.close()

    results = [_result_from_row(row) for row in rows]
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_root": snapshot["snapshot_root_rel"],
        "query": query,
        "count": len(results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the active edu-radar snapshot with SQLite FTS5")
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Skill root containing active_snapshot.json (defaults to this script's parent skill)",
    )
    parser.add_argument("--category")
    parser.add_argument("--status", choices=sorted(VERIFICATION_STATUSES))
    parser.add_argument("--max-risk", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    try:
        payload = search(
            args.skill_dir,
            args.query,
            category=args.category,
            status=args.status,
            max_risk=args.max_risk,
            limit=args.limit,
            rebuild=args.rebuild,
        )
    except SearchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
