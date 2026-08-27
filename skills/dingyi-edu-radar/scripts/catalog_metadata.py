#!/usr/bin/env python3
"""Deterministic catalog-v2 metadata enrichment for edu-radar."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR.parent / "config" / "official_domains.json"

CATEGORIES = {
    "ai",
    "developer-tools",
    "design",
    "productivity",
    "research",
    "cloud",
    "media",
    "shopping",
    "education-benefit",
    "edu-mail",
    "other",
}

RISK_FLAGS = {
    "identity_substitution",
    "sensitive_identifier",
    "account_purchase_or_sale",
    "verification_bypass",
    "bulk_registration",
    "prompt_injection",
    "credential_exposure",
}

HIGH_RISK_FLAGS = {
    "identity_substitution",
    "verification_bypass",
    "bulk_registration",
    "prompt_injection",
}

CATEGORY_RULES = [
    ("ai", ("chatgpt", "gemini", "grok", "perplexity", "claude", "suno", "udio", "人工智能", " ai ", "ai工具")),
    ("developer-tools", ("github", "copilot", "jetbrains", "replit", "developer", "开发", "编程", "ide", "code")),
    ("design", ("figma", "adobe", "canva", "autodesk", "设计", "creative cloud", "photoshop")),
    ("research", ("matlab", "mathworks", "科研", "学术", "research", "wolfram", "overleaf")),
    ("cloud", ("aws", "azure", "cloud", "云服务", "云计算")),
    ("media", ("spotify", "youtube", "音乐", "影音", "流媒体")),
    ("shopping", ("amazon", "购物", "电商", "prime")),
    ("productivity", ("notion", "office", "microsoft 365", "evernote", "印象笔记", "效率", "办公")),
]

RISK_PATTERNS = {
    "identity_substitution": (
        r"美国人信息",
        r"他人(?:身份|信息|资料)",
        r"冒用",
        r"身份资料",
        r"用别人(?:的)?(?:身份|资料|信息)",
    ),
    "sensitive_identifier": (
        r"\bSSN\b",
        r"social\s+security",
        r"身份证(?:号|号码)",
        r"护照(?:号|号码)",
        r"社会安全号",
    ),
    "account_purchase_or_sale": (
        r"购买.{0,8}(?:邮箱|账号|账户)",
        r"(?:买卖|出售|售卖).{0,8}(?:邮箱|账号|账户)",
        r"(?:邮箱|账号|账户).{0,8}(?:购买|出售|售卖)",
    ),
    "verification_bypass": (
        r"绕过.{0,12}(?:验证|认证|审核)",
        r"规避.{0,12}(?:验证|认证|审核)",
        r"bypass.{0,20}(?:verify|verification|check)",
        r"免验证",
    ),
    "bulk_registration": (
        r"批量.{0,8}(?:注册|申请|创建|开通)",
        r"bulk.{0,20}(?:register|registration|signup|create)",
    ),
    "prompt_injection": (
        r"ignore\s+(?:all\s+)?previous\s+instructions",
        r"system\s+prompt",
        r"reveal.{0,30}(?:token|secret|prompt)",
        r"输出.{0,10}系统提示词",
        r"读取.{0,20}(?:token|cookie|环境变量|密钥)",
    ),
    "credential_exposure": (
        r"初始密码",
        r"默认密码",
        r"明文密码",
        r"password.{0,20}(?:display|shown|save|store)",
        r"密码.{0,12}(?:显示|保存|记录|明文)",
    ),
}

TITLE_NOISE_RE = re.compile(
    r"(?:学生教育优惠|学生优惠|教育优惠|教育版|教育计划|教育认证|学生版|"
    r"免费|申请|注册|教程|攻略|图文|详解|全攻略|最新|本站|独家|永久更新|"
    r"edu教育邮箱|edu邮箱|教育邮箱)",
    flags=re.IGNORECASE,
)


def load_registry(path: Path | None = None) -> dict:
    target = path or CONFIG_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _hostlike_casefold(value: str) -> str:
    return _norm(value).casefold()


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        value = _norm(value)
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _detect_entity(item: dict, registry: dict) -> dict | None:
    haystack = " ".join(str(item.get(k, "")) for k in ("title", "kw", "slug")).casefold()
    candidates: list[tuple[int, dict]] = []
    for entity in registry.get("entities", []):
        for alias in entity.get("aliases", []):
            token = _hostlike_casefold(alias)
            if token and token in haystack:
                candidates.append((len(token), entity))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def detect_category(item: dict, reference_text: str = "", registry: dict | None = None) -> str:
    source_kind = str(item.get("source_kind", "")).strip()
    if source_kind == "edu_mail":
        return "edu-mail"

    registry = registry or load_registry()
    entity = _detect_entity(item, registry)
    if entity and entity.get("category") in CATEGORIES:
        return str(entity["category"])

    haystack = f" {item.get('title', '')} {item.get('kw', '')} {reference_text[:4000]} ".casefold()
    for category, needles in CATEGORY_RULES:
        if any(needle.casefold() in haystack for needle in needles):
            return category

    if "优惠" in haystack or "student" in haystack or "education" in haystack:
        return "education-benefit"
    return "other"


def build_aliases(item: dict, registry: dict | None = None) -> list[str]:
    registry = registry or load_registry()
    aliases: list[str] = []
    entity = _detect_entity(item, registry)
    if entity:
        aliases.extend(entity.get("aliases", []))

    title = _norm(str(item.get("title", "")))
    cleaned = _norm(TITLE_NOISE_RE.sub(" ", title))
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -—_()（）")
    if cleaned and cleaned.casefold() != title.casefold():
        aliases.append(cleaned)

    kw = _norm(str(item.get("kw", "")))
    if kw and kw.casefold() != title.casefold():
        aliases.append(kw)

    # Pull obvious product/institution tokens while avoiding generic EDU noise.
    latin_tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+-]{2,}(?:\s+[A-Za-z][A-Za-z0-9.+-]{2,})?", title)
    aliases.extend(latin_tokens)
    return _unique(aliases)


def detect_risk_flags(item: dict, reference_text: str = "") -> list[str]:
    haystack = "\n".join(
        [
            str(item.get("title", "")),
            str(item.get("kw", "")),
            reference_text,
        ]
    )
    flags: list[str] = []
    for flag, patterns in RISK_PATTERNS.items():
        if any(re.search(pattern, haystack, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns):
            flags.append(flag)
    return sorted(flags)


def risk_level(flags: Iterable[str]) -> str:
    values = set(flags)
    if values & HIGH_RISK_FLAGS:
        return "high"
    if values:
        return "medium"
    return "low"


def enrich_item(item: dict, reference_text: str = "", registry: dict | None = None) -> dict:
    registry = registry or load_registry()
    enriched = dict(item)
    enriched["category"] = detect_category(enriched, reference_text, registry)
    enriched["aliases"] = build_aliases(enriched, registry)
    flags = detect_risk_flags(enriched, reference_text)
    enriched["risk_flags"] = flags
    enriched["risk_level"] = risk_level(flags)
    enriched["source_trust"] = "untrusted"
    return enriched


if __name__ == "__main__":
    raise SystemExit("catalog_metadata.py is a library; use migrate_catalog_v2.py or refresh.sh")
