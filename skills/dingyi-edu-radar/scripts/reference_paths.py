#!/usr/bin/env python3
"""Cross-platform filesystem naming for reference documents.

Logical catalog slugs remain stable and human/search-facing. Only the physical
Markdown filename is shortened when a slug would be unsafe or too long on common
Windows filesystems.
"""

from __future__ import annotations

import hashlib
import re


MAX_FILENAME_BYTES = 120
SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9%._-]+$")
WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _hashed_filename(slug: str) -> str:
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:24]
    return f"ref-{digest}.md"


def reference_filename(slug: str) -> str:
    """Return a deterministic, Windows-safe Markdown filename for a logical slug."""
    if not isinstance(slug, str) or not slug:
        raise ValueError("slug must be a non-empty string")

    candidate = f"{slug}.md"
    stem = slug.casefold()
    safe = (
        SAFE_SLUG_RE.fullmatch(slug) is not None
        and stem not in WINDOWS_RESERVED
        and not slug.endswith((".", " "))
        and len(candidate.encode("utf-8")) <= MAX_FILENAME_BYTES
    )
    return candidate if safe else _hashed_filename(slug)
