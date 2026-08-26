#!/usr/bin/env bash
# Record a named candump log with a metadata sidecar, so a capture taken in a
# cold driveway is still interpretable a month later.
#
#   ./capture.sh baseline                 record until Ctrl-C
#   ./capture.sh avh-button -t 30         record 30 seconds
#   ./capture.sh doors -n "left rear x3"  attach a note
#
# Convention that makes event_diff.py useful:
#   1. ./capture.sh baseline -t 60      touch nothing
#   2. ./capture.sh <event> -t 60       actuate ONE control, repeatedly
#   3. tools/event_diff.py logs/baseline-*.log logs/<event>-*.log

set -euo pipefail

IFACE="${IFACE:-can0}"
OUTDIR="${OUTDIR:-$(dirname "$0")/logs}"
LABEL=""
SECS=""
NOTE=""

usage() { sed -n '2,14p' "$0" | sed 's/^# \?//'; exit "${1:-0}"; }

[[ $# -ge 1 ]] || usage 1
LABEL="$1"; shift
[[ "$LABEL" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo "label must be [a-zA-Z0-9._-]" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t) SECS="$2"; shift 2 ;;
    -n) NOTE="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

ip link show "$IFACE" 2>/dev/null | grep -q 'state UP' \
  || { echo "$IFACE is not up -- run ./bringup.sh first" >&2; exit 1; }

mkdir -p "$OUTDIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
BASE="$OUTDIR/${LABEL}-${STAMP}"

{
  echo "label:     $LABEL"
  echo "started:   $(date -Is)"
  echo "interface: $IFACE"
  echo "note:      ${NOTE:-(none)}"
  echo "link:"
  ip -details link show "$IFACE" | sed 's/^/  /'
} > "$BASE.meta"

echo "Recording -> $BASE.log"
[[ -n "$SECS" ]] && echo "Duration: ${SECS}s" || echo "Ctrl-C to stop."
echo

# candump -l writes candump-<ts>.log into $PWD; capture to our path instead.
if [[ -n "$SECS" ]]; then
  timeout "$SECS" candump -L "$IFACE" | tee "$BASE.log" | \
    awk 'NR%200==0 {printf "\r  %d frames", NR; fflush()}' || true
else
  candump -L "$IFACE" | tee "$BASE.log" | \
    awk 'NR%200==0 {printf "\r  %d frames", NR; fflush()}' || true
fi

echo
FRAMES="$(wc -l < "$BASE.log")"
IDS="$(awk '{print $3}' "$BASE.log" | cut -d'#' -f1 | sort -u | wc -l)"
echo "frames:    $FRAMES" >> "$BASE.meta"
echo "unique_ids: $IDS"   >> "$BASE.meta"
echo "ended:     $(date -Is)" >> "$BASE.meta"
printf '\nDone. %s frames, %s unique IDs.\n' "$FRAMES" "$IDS"
[[ "$FRAMES" -eq 0 ]] && echo "WARNING: empty capture -- bus asleep, or wrong config." >&2
exit 0
