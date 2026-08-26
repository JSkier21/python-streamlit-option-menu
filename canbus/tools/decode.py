#!/usr/bin/env python3
"""Check a capture against a DBC, and decode what it covers.

On a 2024 Crosstrek no DBC is known to fit exactly, so start with coverage
rather than decode: it tells you how much of an existing Subaru DBC actually
applies before you trust any decoded signal.

    ./decode.py --dbc subaru_global_2017_generated.dbc logs/baseline-*.log
    ./decode.py --dbc <file> logs/baseline-*.log --decode --id 321

Requires: pip install cantools
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canlog import read_log  # noqa: E402

try:
    import cantools
except ImportError:
    print("error: cantools not installed.  pip install cantools", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--dbc", required=True)
    ap.add_argument("--decode", action="store_true", help="print decoded signals")
    ap.add_argument("--id", help="restrict --decode to one hex ID, e.g. 321")
    ap.add_argument("--limit", type=int, default=40, help="max decoded frames to print")
    args = ap.parse_args()

    db = cantools.database.load_file(args.dbc)
    known = {m.frame_id: m for m in db.messages}

    counts: Counter[int] = Counter()
    dlcs: dict[int, set[int]] = {}
    for frame in read_log(args.log):
        if frame.remote:
            continue
        counts[frame.can_id] += 1
        dlcs.setdefault(frame.can_id, set()).add(len(frame.data))

    if not counts:
        print("error: no frames parsed from the log.", file=sys.stderr)
        return 1

    matched = {i for i in counts if i in known}
    unmatched = sorted(set(counts) - matched, key=lambda i: -counts[i])

    total = sum(counts.values())
    matched_frames = sum(counts[i] for i in matched)
    print(f"DBC:  {args.dbc}  ({len(known)} messages defined)")
    print(f"Log:  {args.log}  ({total} frames, {len(counts)} unique IDs)")
    print()
    print(f"ID coverage:     {len(matched)}/{len(counts)} "
          f"({100 * len(matched) / len(counts):.0f}%)")
    print(f"Frame coverage:  {matched_frames}/{total} "
          f"({100 * matched_frames / total:.0f}%)")
    print()

    # A DBC that matches IDs but disagrees on length is a DBC for a different
    # model year. Worth surfacing loudly -- decoded values would be garbage.
    mismatched = []
    for i in sorted(matched):
        msg = known[i]
        observed = dlcs[i]
        if msg.length not in observed:
            mismatched.append((i, msg.name, msg.length, sorted(observed)))
    if mismatched:
        print(f"WARNING: {len(mismatched)} matched ID(s) disagree on length.")
        print("This is the signature of a DBC from a different platform or year.")
        print("Treat decoded values from these as unreliable.")
        for i, name, expect, saw in mismatched[:10]:
            print(f"  {i:03X} {name:<32} dbc says {expect}, bus shows {saw}")
        print()

    if unmatched:
        print(f"Top unmatched IDs (your reverse-engineering worklist):")
        for i in unmatched[:20]:
            print(f"  {i:03X}  {counts[i]:6d} frames  dlc {sorted(dlcs[i])}")
        print()

    if not args.decode:
        print("Re-run with --decode to print decoded signals.")
        return 0

    want = int(args.id, 16) if args.id else None
    shown = 0
    for frame in read_log(args.log):
        if frame.remote or frame.can_id not in known:
            continue
        if want is not None and frame.can_id != want:
            continue
        msg = known[frame.can_id]
        try:
            decoded = msg.decode(frame.data, decode_choices=False)
        except Exception as exc:  # length/format mismatch, out-of-range value
            print(f"{frame.ts:.3f} {frame.id_hex} {msg.name}: undecodable ({exc})")
        else:
            fields = "  ".join(f"{k}={v}" for k, v in decoded.items())
            print(f"{frame.ts:.3f} {frame.id_hex} {msg.name}: {fields}")
        shown += 1
        if shown >= args.limit:
            print(f"\n(stopped at --limit {args.limit})")
            break
    if shown == 0:
        print("Nothing decoded -- no frames matched that filter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
