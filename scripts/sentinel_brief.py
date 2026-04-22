"""
CLI runner for the Fourseat Sentinel daily briefing.

Usage:
    python -m scripts.sentinel_brief               # fetch 10, render markdown
    python -m scripts.sentinel_brief --limit 20    # larger batch
    python -m scripts.sentinel_brief --dry-run     # fetch + print, skip DB writes
    python -m scripts.sentinel_brief --render-only # re-render from existing DB rows
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.sentinel import (  # noqa: E402
    fetch_important_emails,
    init_db,
    render_daily_brief,
    run_daily_brief,
    triage_batch,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fourseat Sentinel daily briefing")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print, skip DB writes")
    parser.add_argument("--render-only", action="store_true", help="Render from existing DB rows")
    args = parser.parse_args()

    if args.render_only:
        print(render_daily_brief(limit=args.limit))
        return 0

    if args.dry_run:
        msgs = fetch_important_emails(limit=args.limit)
        for m in msgs:
            print(f"[{m.received_at}] {m.sender} :: {m.subject}")
        print(f"\nFetched {len(msgs)} messages (dry run).")
        return 0

    init_db()
    result = run_daily_brief(limit=args.limit)
    print(result["brief_markdown"])
    print(f"\n<!-- processed={result['processed']} fetched={result['fetched']} at {result['generated_at']} -->")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
