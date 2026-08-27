#!/usr/bin/env bash
# refresh.sh — build, validate, and atomically activate an edu-radar snapshot.
#
# Pipeline:
#   scrape_snapshot.py -> snapshot_enrich.py -> safe_publish.py
#   staged UNTRUSTED data -> category/aliases/risk_flags -> official verification
#   -> schema/quality validation -> immutable snapshot -> atomic active pointer
#
# The scraper writes these explicit trust-boundary markers into every reference:
#   UNTRUSTED_EXTERNAL_DATA
#   BEGIN_UNTRUSTED_REFERENCE_DATA
#   END_UNTRUSTED_REFERENCE_DATA
# It also emits source_kind=benefit|edu_mail for catalog-v2 enrichment.
#
# No stage writes the active knowledge base directly. Any scrape, parse, enrichment,
# validation, or publication error exits before active_snapshot.json is switched.
#
# Usage:
#   bash scripts/refresh.sh
#   bash scripts/refresh.sh --full   # accepted for compatibility; refresh is snapshot-based
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SNAPSHOT_ENRICH="$SCRIPT_DIR/snapshot_enrich.py"
SAFE_PUBLISH="$SCRIPT_DIR/safe_publish.py"
SCRAPER="$SCRIPT_DIR/scrape_snapshot.py"
ACTIVE_POINTER="$SKILL_DIR/active_snapshot.json"

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo "ERROR: Python not found: $PYTHON" >&2; exit 1; }
"$PYTHON" -c "import bs4, lxml" 2>/dev/null || {
  echo "ERROR: python3 requires beautifulsoup4 and lxml" >&2
  echo "Install with: pip3 install --user beautifulsoup4 lxml" >&2
  exit 1
}
for required in "$SCRAPER" "$SNAPSHOT_ENRICH" "$SAFE_PUBLISH"; do
  [ -f "$required" ] || { echo "ERROR: missing pipeline component: $required" >&2; exit 1; }
done

case "${1:-}" in
  "") ;;
  --full)
    echo "[info] --full is retained for compatibility; every refresh now builds a complete immutable snapshot."
    ;;
  *)
    echo "ERROR: unknown argument: $1" >&2
    exit 2
    ;;
esac

MIN_ARTICLE_COUNT="${EDU_RADAR_MIN_ARTICLE_COUNT:-50}"
MIN_ARTICLE_RATIO="${EDU_RADAR_MIN_ARTICLE_RATIO:-0.80}"
ALLOW_SHRINK="${EDU_RADAR_ALLOW_SHRINK:-0}"
VERIFY_OFFICIAL="${EDU_RADAR_VERIFY_OFFICIAL:-1}"
VERIFY_WORKERS="${EDU_RADAR_VERIFY_WORKERS:-8}"
BASE_URL="${EDU_RADAR_BASE_URL:-https://www.edumails.cn}"
KEEP_SNAPSHOTS="${EDU_RADAR_KEEP_SNAPSHOTS:-3}"
REQUEST_TIMEOUT="${EDU_RADAR_REQUEST_TIMEOUT:-30}"
MAX_LIST_PAGES="${EDU_RADAR_MAX_LIST_PAGES:-100}"
FETCH_SLEEP="${EDU_RADAR_FETCH_SLEEP:-0.25}"

SNAPSHOT_ID="${EDU_RADAR_SNAPSHOT_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
STAGE_ROOT="$(mktemp -d "$SKILL_DIR/.refresh-stage.XXXXXX")"
cleanup() {
  rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT

printf '[1/4] Build staged third-party snapshot (%s)...\n' "$SNAPSHOT_ID"
"$PYTHON" "$SCRAPER" \
  --snapshot-root "$STAGE_ROOT" \
  --base-url "$BASE_URL" \
  --min-count "$MIN_ARTICLE_COUNT" \
  --request-timeout "$REQUEST_TIMEOUT" \
  --max-pages "$MAX_LIST_PAGES" \
  --sleep "$FETCH_SLEEP"

printf '[2/4] Enrich catalog-v2 metadata and verify official sources...\n'
enrich_args=(
  --snapshot-root "$STAGE_ROOT"
  --snapshot-id "$SNAPSHOT_ID"
  --workers "$VERIFY_WORKERS"
)
if [ "$VERIFY_OFFICIAL" = "1" ]; then
  enrich_args+=(--verify-official)
elif [ "$VERIFY_OFFICIAL" = "0" ]; then
  enrich_args+=(--offline)
  echo "[warning] EDU_RADAR_VERIFY_OFFICIAL=0: official verification disabled for this refresh."
else
  echo "ERROR: EDU_RADAR_VERIFY_OFFICIAL must be 0 or 1" >&2
  exit 2
fi
"$PYTHON" "$SNAPSHOT_ENRICH" "${enrich_args[@]}"

printf '[3/4] Validate complete staging snapshot and atomically activate...\n'
publish_args=(
  --skill-dir "$SKILL_DIR"
  --stage-dir "$STAGE_ROOT"
  --min-count "$MIN_ARTICLE_COUNT"
  --min-ratio "$MIN_ARTICLE_RATIO"
  --keep-snapshots "$KEEP_SNAPSHOTS"
)
if [ "$ALLOW_SHRINK" = "1" ]; then
  publish_args+=(--allow-shrink)
  echo "[warning] EDU_RADAR_ALLOW_SHRINK=1: abnormal shrink guard explicitly overridden."
elif [ "$ALLOW_SHRINK" != "0" ]; then
  echo "ERROR: EDU_RADAR_ALLOW_SHRINK must be 0 or 1" >&2
  exit 2
fi
"$PYTHON" "$SAFE_PUBLISH" "${publish_args[@]}"

printf '[4/4] Active snapshot\n'
"$PYTHON" - "$ACTIVE_POINTER" <<'PYEOF'
import json
import sys
from pathlib import Path

pointer = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(f"  snapshot_id: {pointer['snapshot_id']}")
print(f"  snapshot_root: {pointer['snapshot_root']}")
print(f"  activated_at: {pointer['activated_at']}")
PYEOF

echo "Refresh complete. The active pointer was switched only after all validation gates passed."
