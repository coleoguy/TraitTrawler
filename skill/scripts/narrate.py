#!/usr/bin/env python3
"""Short helper to emit consistent, style-guide-compliant status lines.

Used by subagents so they do not have to memorize the templates in
references/talkative_style.md. Prints to stdout; the Manager reads
stdout back.
"""
from __future__ import annotations

import argparse
import sys


TEMPLATES = {
    "phase_open":
        "Phase {phase}: {summary}",
    "batch_close":
        ("Batch {n} done. {rows} rows written, {review} to review, "
         "{adjudicated} adjudicated. Interesting: {surprise}"),
    "surprise":
        "Heads up from batch {n}: {observation}. Might matter because {why}.",
    "cost_warning":
        ("Cost note: on track for ~${projected} for full corpus of {papers} "
         "papers (budgeted {budget}). Say 'throttle' to drop extractor to Sonnet."),
    "pause_point":
        ("Pausing. Three options:\n  1. {default} -- say 'go' to continue.\n"
         "  2. {alt}\n  3. {edit}"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=sorted(TEMPLATES))
    ap.add_argument("pairs", nargs="*", help="key=value pairs for template")
    args = ap.parse_args()
    kv: dict[str, str] = {}
    for p in args.pairs:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k] = v
    try:
        print(TEMPLATES[args.kind].format(**kv))
    except KeyError as e:
        print(f"missing template key: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
