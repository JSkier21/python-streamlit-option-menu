#!/usr/bin/env python3
"""Isolate the frame carrying a control input by diffing two captures.

Record a baseline with the car untouched, then a second capture in which you
actuate exactly one control, repeatedly. This finds bit positions that took a
value in the event capture that they never took in the baseline.

    ./event_diff.py logs/baseline-*.log logs/avh-button-*.log

Ranking favours small, clean changes: a button press is usually one or two bits
on one ID. Rolling counters and checksums move constantly, so bytes that were
already noisy in the baseline are demoted rather than reported as signal.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canlog import read_log  # noqa: E402

# A byte taking more than this many distinct values in the baseline is treated
# as a counter, checksum, or continuous sensor rather than a discrete signal.
NOISY_BYTE_THRESHOLD = 16


def profile(path: str) -> dict[tuple[str, int], list[set[int]]]:
    """Map (id_hex, dlc) -> per-byte sets of observed values."""
    seen: dict[tuple[str, int], list[set[int]]] = {}
    for frame in read_log(path):
        if frame.remote:
            continue
        key = (frame.id_hex, len(frame.data))
        slots = seen.get(key)
        if slots is None:
            slots = [set() for _ in frame.data]
            seen[key] = slots
        for i, byte in enumerate(frame.data):
            slots[i].add(byte)
    return seen


def count_frames(path: str) -> int:
    return sum(1 for _ in read_log(path))


def novel_bits(base_vals: set[int], event_vals: set[int]) -> int:
    """Bits whose value in the event capture never occurred in the baseline.

    Catches both directions: a bit that goes high but was always low at rest,
    and a bit that goes low but was always high at rest.
    """
    ever_high = 0
    ever_low = 0
    for v in base_vals:
        ever_high |= v
        ever_low |= (~v) & 0xFF

    always_low = (~ever_high) & 0xFF   # never observed high in baseline
    always_high = (~ever_low) & 0xFF   # never observed low in baseline

    novel = 0
    for v in event_vals:
        novel |= v & always_low          # went high, never had
        novel |= (~v) & always_high      # went low, never had
    return novel & 0xFF


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline")
    ap.add_argument("event")
    ap.add_argument("-n", "--top", type=int, default=15, help="candidates to show")
    ap.add_argument("--all", action="store_true", help="include noisy bytes")
    args = ap.parse_args()

    for p in (args.baseline, args.event):
        if not Path(p).exists():
            print(f"error: no such file: {p}", file=sys.stderr)
            return 1

    base = profile(args.baseline)
    event = profile(args.event)

    nb, ne = count_frames(args.baseline), count_frames(args.event)
    print(f"baseline  {args.baseline}  {nb} frames, {len(base)} id/dlc pairs")
    print(f"event     {args.event}  {ne} frames, {len(event)} id/dlc pairs")
    if nb == 0 or ne == 0:
        print("\nerror: an empty capture cannot be diffed.", file=sys.stderr)
        return 1
    print()

    new_ids = sorted(k for k in event if k not in base)
    if new_ids:
        print("IDs present only in the event capture -- strongest signal:")
        for id_hex, dlc in new_ids:
            print(f"  {id_hex}  [{dlc}]")
        print()

    candidates = []
    for key, ev_slots in event.items():
        if key not in base:
            continue
        base_slots = base[key]
        changes = []
        for i, ev_vals in enumerate(ev_slots):
            if i >= len(base_slots):
                continue
            base_vals = base_slots[i]
            mask = novel_bits(base_vals, ev_vals)
            if not mask:
                continue
            noisy = len(base_vals) > NOISY_BYTE_THRESHOLD
            if noisy and not args.all:
                continue
            changes.append((i, mask, len(base_vals), noisy))
        if changes:
            total_bits = sum(bin(m).count("1") for _, m, _, _ in changes)
            candidates.append((total_bits, len(changes), key, changes))

    if not candidates:
        print("No novel bits found on shared IDs.")
        print("Try: a longer event capture, more repetitions of the input,")
        print("or --all if the signal may sit in a byte that is noisy at rest.")
        return 0

    # Fewest changed bits first: a discrete control should be a small change.
    candidates.sort(key=lambda c: (c[0], c[1]))

    print(f"Candidate frames, cleanest change first (top {args.top}):")
    print()
    for total_bits, _, (id_hex, dlc), changes in candidates[: args.top]:
        print(f"  ID {id_hex}  [{dlc}]   {total_bits} novel bit(s)")
        for i, mask, base_variety, noisy in changes:
            bits = ", ".join(str(b) for b in range(8) if mask >> b & 1)
            tag = "  (noisy at rest)" if noisy else ""
            print(f"      byte {i}: mask 0x{mask:02X}  bit(s) {bits}"
                  f"   baseline had {base_variety} value(s){tag}")
        print()

    print("Confirm a candidate before believing it:")
    print("  1. Re-run both captures. A real signal reproduces; noise does not.")
    print("  2. Watch it live:  cansniffer -c can0")
    print("  3. Capture the inverse (turn the feature OFF) and check the bit clears.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
