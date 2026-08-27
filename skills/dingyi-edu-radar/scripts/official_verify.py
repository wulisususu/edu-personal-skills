#!/usr/bin/env python3
"""Conservative secondary verification for official sources referenced by catalog items."""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = SCRIPT_DIR.parent / "config" / "official_domains.json"
URL_RE = re.compile(r"https?://[^\s)\]}>\"']+", re.IGNORECASE)


def load_registry(path: Path | None = None) -> dict:
    return json.loads((path or REGISTRY_PATH).read_text(encoding="utf-8"))


def extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:!?，。；：！？）】》")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _domain_matches(host: str, domain: str) -> bool:
    domain = domain.lower().rstrip(".")
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def _is_blocked(host: str, registry: dict) -> bool:
    return any(_domain_matches(host, d) for d in registry.get("blocked_domains", []))


def _entity_for_item(item: dict, registry: dict) -> dict | None:
    haystack = " ".join(
        [
            str(item.get("title", "")),
            str(item.get("kw", "")),
            " ".join(item.get("aliases", []) if isinstance(item.get("aliases"), list) else []),
        ]
    ).casefold()
    matches: list[tuple[int, dict]] = []
    for entity in registry.get("entities", []):
        for alias in entity.get("aliases", []):
            token = str(alias).strip().casefold()
            if token and token in haystack:
                matches.append((len(token), entity))
    if not matches:
        return None
    matches.sort(key=lambda pair: pair[0], reverse=True)
    return matches[0][1]


def is_academic_domain(host: str) -> bool:
    host = host.lower().rstrip(".")
    if not host:
        return False
    if host.endswith(".edu"):
        return True
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in {"edu", "ac"}:
        return True
    return False


def fetch_http_status(url: str, timeout: float = 8.0) -> int:
    headers = {"User-Agent": "edu-radar-official-verifier/1.0"}
    request = urllib.request.Request(url, headers=headers, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.getcode())
    except urllib.error.HTTPError as exc:
        if exc.code not in {405, 501}:
            return int(exc.code)
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.getcode())


def _verification_base() -> dict:
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


def _select_candidate(item: dict, urls: list[str], registry: dict) -> tuple[str, str, str] | None:
    entity = _entity_for_item(item, registry)
    if entity:
        official_domains = [str(x).lower() for x in entity.get("domains", [])]
        for url in urls:
            host = _host(url)
            if _is_blocked(host, registry):
                continue
            if any(_domain_matches(host, domain) for domain in official_domains):
                return url, host, "configured-domain"

    if item.get("source_kind") == "edu_mail":
        for url in urls:
            host = _host(url)
            if _is_blocked(host, registry):
                continue
            if is_academic_domain(host):
                return url, host, "academic-domain"
    return None


def verify_item(
    item: dict,
    reference_text: str,
    *,
    registry: dict | None = None,
    fetcher: Callable[[str], int] | None = None,
) -> dict:
    registry = registry or load_registry()
    fetcher = fetcher or fetch_http_status
    result = _verification_base()

    urls = extract_urls(reference_text)
    candidate = _select_candidate(item, urls, registry)
    if not candidate:
        return result

    url, host, method = candidate
    result.update(
        {
            "status": "candidate",
            "candidate_url": url,
            "candidate_domain": host,
            "method": method,
        }
    )

    try:
        status = int(fetcher(url))
    except (OSError, TimeoutError, socket.timeout, urllib.error.URLError, ValueError):
        result["status"] = "failed"
        return result
    except Exception:
        # Verification is deliberately non-fatal to the refresh pipeline.
        result["status"] = "failed"
        return result

    result["http_status"] = status
    if 200 <= status < 400:
        result.update(
            {
                "status": "verified",
                "official_url": url,
                "official_domain": host,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    else:
        result["status"] = "failed"
    return result


if __name__ == "__main__":
    raise SystemExit("official_verify.py is a library; use refresh.sh")
