#!/usr/bin/env python3
"""Portable edu-radar refresh orchestration for Linux, macOS, and Windows.

This module is the single source of truth for refresh orchestration. Platform
wrappers (`refresh.sh` / `refresh.ps1`) only locate Python and delegate here.

Pipeline:
    scrape_snapshot.py -> snapshot_enrich.py -> safe_publish.py

No child stage mutates the active knowledge base directly. The publisher only
switches `active_snapshot.json` after validation succeeds.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RefreshError(RuntimeError):
    """Raised when portable refresh configuration or execution is unsafe."""


class RefreshConfig:
    def __init__(
        self,
        *,
        skill_dir: Path,
        min_article_count: int,
        min_article_ratio: float,
        allow_shrink: bool,
        verify_official: bool,
        verify_workers: int,
        base_url: str,
        keep_snapshots: int,
        request_timeout: float,
        max_list_pages: int,
        fetch_sleep: float,
        snapshot_id: str,
    ) -> None:
        self.skill_dir = skill_dir
        self.scripts_dir = skill_dir / "scripts"
        self.min_article_count = min_article_count
        self.min_article_ratio = min_article_ratio
        self.allow_shrink = allow_shrink
        self.verify_official = verify_official
        self.verify_workers = verify_workers
        self.base_url = base_url.rstrip("/")
        self.keep_snapshots = keep_snapshots
        self.request_timeout = request_timeout
        self.max_list_pages = max_list_pages
        self.fetch_sleep = fetch_sleep
        self.snapshot_id = snapshot_id

    @property
    def scraper(self) -> Path:
        return self.scripts_dir / "scrape_snapshot.py"

    @property
    def enricher(self) -> Path:
        return self.scripts_dir / "snapshot_enrich.py"

    @property
    def publisher(self) -> Path:
        return self.scripts_dir / "safe_publish.py"

    @property
    def active_pointer(self) -> Path:
        return self.skill_dir / "active_snapshot.json"


def _int_env(env: Mapping[str, str], name: str, default: int, *, minimum: int = 0) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RefreshError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise RefreshError(f"{name} must be >= {minimum}, got {value}")
    return value


def _float_env(
    env: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
    strictly_greater: bool = False,
) -> float:
    raw = env.get(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RefreshError(f"{name} must be numeric, got {raw!r}") from exc
    if strictly_greater:
        if value <= minimum:
            raise RefreshError(f"{name} must be > {minimum}, got {value}")
    elif value < minimum:
        raise RefreshError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise RefreshError(f"{name} must be <= {maximum}, got {value}")
    return value


def _bool_env(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "1" if default else "0")
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise RefreshError(f"{name} must be 0 or 1, got {raw!r}")


def _default_snapshot_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{os.getpid()}"


def load_config(skill_dir: Path, env: Mapping[str, str] | None = None) -> RefreshConfig:
    """Load and strictly validate platform-neutral refresh configuration."""
    values = os.environ if env is None else env
    skill_dir = Path(skill_dir).resolve()
    if not skill_dir.is_dir():
        raise RefreshError(f"skill directory does not exist: {skill_dir}")

    snapshot_id = values.get("EDU_RADAR_SNAPSHOT_ID", _default_snapshot_id())
    if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise RefreshError(f"EDU_RADAR_SNAPSHOT_ID is unsafe: {snapshot_id!r}")

    config = RefreshConfig(
        skill_dir=skill_dir,
        min_article_count=_int_env(values, "EDU_RADAR_MIN_ARTICLE_COUNT", 50, minimum=1),
        min_article_ratio=_float_env(
            values,
            "EDU_RADAR_MIN_ARTICLE_RATIO",
            0.80,
            minimum=0.0,
            maximum=1.0,
            strictly_greater=True,
        ),
        allow_shrink=_bool_env(values, "EDU_RADAR_ALLOW_SHRINK", False),
        verify_official=_bool_env(values, "EDU_RADAR_VERIFY_OFFICIAL", True),
        verify_workers=_int_env(values, "EDU_RADAR_VERIFY_WORKERS", 8, minimum=1),
        base_url=values.get("EDU_RADAR_BASE_URL", "https://www.edumails.cn"),
        keep_snapshots=_int_env(values, "EDU_RADAR_KEEP_SNAPSHOTS", 3, minimum=1),
        request_timeout=_float_env(
            values,
            "EDU_RADAR_REQUEST_TIMEOUT",
            30.0,
            minimum=0.0,
            strictly_greater=True,
        ),
        max_list_pages=_int_env(values, "EDU_RADAR_MAX_LIST_PAGES", 100, minimum=1),
        fetch_sleep=_float_env(values, "EDU_RADAR_FETCH_SLEEP", 0.25, minimum=0.0),
        snapshot_id=snapshot_id,
    )

    if not config.base_url.startswith(("http://", "https://")):
        raise RefreshError("EDU_RADAR_BASE_URL must start with http:// or https://")
    for component in (config.scraper, config.enricher, config.publisher):
        if not component.is_file():
            raise RefreshError(f"missing pipeline component: {component}")
    return config


def ensure_parser_dependencies() -> None:
    missing = [name for name in ("bs4", "lxml") if importlib.util.find_spec(name) is None]
    if missing:
        raise RefreshError(
            "missing parser dependencies: "
            + ", ".join(missing)
            + ". Install with: python -m pip install beautifulsoup4 lxml"
        )


def _execute(command: Sequence[str], *, runner=None) -> None:
    if runner is None:
        try:
            subprocess.run(list(command), check=True)
        except subprocess.CalledProcessError as exc:
            raise RefreshError(f"pipeline command failed with exit code {exc.returncode}: {command[0]}") from exc
    else:
        try:
            runner(list(command), check=True)
        except RefreshError:
            raise
        except subprocess.CalledProcessError as exc:
            raise RefreshError(f"pipeline command failed with exit code {exc.returncode}: {command[0]}") from exc
        except Exception as exc:
            raise RefreshError(f"pipeline command failed: {exc}") from exc


def run_refresh(config: RefreshConfig, *, runner=None, full: bool = False) -> dict:
    """Build, validate, and publish one complete snapshot.

    `full` is retained only for CLI compatibility; every refresh is already a full
    immutable snapshot build.
    """
    if full:
        print("[info] --full is retained for compatibility; every refresh builds a complete immutable snapshot.")

    stage_dir = Path(tempfile.mkdtemp(prefix=".refresh-stage.", dir=str(config.skill_dir)))
    python = sys.executable
    try:
        print(f"[1/4] Build staged third-party snapshot ({config.snapshot_id})...")
        _execute(
            [
                python,
                str(config.scraper),
                "--snapshot-root",
                str(stage_dir),
                "--base-url",
                config.base_url,
                "--min-count",
                str(config.min_article_count),
                "--request-timeout",
                str(config.request_timeout),
                "--max-pages",
                str(config.max_list_pages),
                "--sleep",
                str(config.fetch_sleep),
            ],
            runner=runner,
        )

        print("[2/4] Enrich catalog-v2 metadata and verify official sources...")
        enrich = [
            python,
            str(config.enricher),
            "--snapshot-root",
            str(stage_dir),
            "--snapshot-id",
            config.snapshot_id,
            "--workers",
            str(config.verify_workers),
        ]
        if config.verify_official:
            enrich.append("--verify-official")
        else:
            enrich.append("--offline")
            print("[warning] EDU_RADAR_VERIFY_OFFICIAL=0: official verification disabled for this refresh.")
        _execute(enrich, runner=runner)

        print("[3/4] Validate complete staging snapshot and atomically activate...")
        publish = [
            python,
            str(config.publisher),
            "--skill-dir",
            str(config.skill_dir),
            "--stage-dir",
            str(stage_dir),
            "--min-count",
            str(config.min_article_count),
            "--min-ratio",
            str(config.min_article_ratio),
            "--keep-snapshots",
            str(config.keep_snapshots),
        ]
        if config.allow_shrink:
            publish.append("--allow-shrink")
            print("[warning] EDU_RADAR_ALLOW_SHRINK=1: abnormal shrink guard explicitly overridden.")
        _execute(publish, runner=runner)

        try:
            pointer = json.loads(config.active_pointer.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise RefreshError(f"publisher did not leave a valid active pointer: {config.active_pointer}") from exc

        print("[4/4] Active snapshot")
        for key in ("snapshot_id", "snapshot_root", "activated_at"):
            print(f"  {key}: {pointer.get(key)}")
        print("Refresh complete. The active pointer was switched only after all validation gates passed.")
        return pointer
    finally:
        # safe_publish may have moved the entire stage directory into `.snapshots/`;
        # ignore the now-missing source path in that successful case.
        shutil.rmtree(stage_dir, ignore_errors=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, validate, and atomically activate an edu-radar snapshot on Linux, macOS, or Windows."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="compatibility flag; refresh is already full immutable-snapshot based",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        ensure_parser_dependencies()
        config = load_config(Path(__file__).resolve().parent.parent)
        run_refresh(config, full=args.full)
    except RefreshError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
