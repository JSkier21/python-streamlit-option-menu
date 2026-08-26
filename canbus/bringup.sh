#!/usr/bin/env bash
# Probe a vehicle CAN bus for the correct bit timing, then leave the interface
# up in the configuration that saw traffic.
#
# ALWAYS brings the interface up listen-only. This script never transmits.
#
#   ./bringup.sh              probe every candidate config, keep the winner
#   ./bringup.sh classic500   force one config, skip probing
#   IFACE=can1 ./bringup.sh   operate on a different interface

set -euo pipefail

IFACE="${IFACE:-can0}"
PROBE_SECS="${PROBE_SECS:-6}"
SUDO=""
[[ $EUID -eq 0 ]] || SUDO="sudo"

# name          kind     nominal   data      why
CONFIGS=(
  "classic500   classic  500000    -         powertrain / OBD-II, most likely"
  "fd500_2m     fd       500000    2000000   CAN FD, common on 2023+ platforms"
  "fd500_5m     fd       500000    5000000   CAN FD, faster data phase"
  "classic125   classic  125000    -         body / comfort bus"
  "classic250   classic  250000    -         uncommon, worth ruling out"
)

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m%s\033[0m\n' "$*"; }

command -v candump >/dev/null || die "can-utils not installed (candump missing)"
ip link show "$IFACE" >/dev/null 2>&1 || die "interface $IFACE not present -- is the CANable plugged in and gs_usb loaded?"

link_down() { $SUDO ip link set "$IFACE" down 2>/dev/null || true; }

# Returns 0 if the interface came up, 1 if the kernel/firmware rejected the config.
configure() {
  local kind="$1" nominal="$2" data="$3"
  link_down
  if [[ "$kind" == "fd" ]]; then
    $SUDO ip link set "$IFACE" type can \
      bitrate "$nominal" dbitrate "$data" fd on listen-only on 2>/dev/null || return 1
  else
    $SUDO ip link set "$IFACE" type can \
      bitrate "$nominal" listen-only on 2>/dev/null || return 1
  fi
  $SUDO ip link set "$IFACE" up 2>/dev/null || return 1
  return 0
}

# CAN controller state: ERROR-ACTIVE / ERROR-WARNING / ERROR-PASSIVE / BUS-OFF / STOPPED
can_state() {
  ip -details link show "$IFACE" 2>/dev/null \
    | grep -oE '(ERROR-ACTIVE|ERROR-WARNING|ERROR-PASSIVE|BUS-OFF|STOPPED)' \
    | head -1
}

frame_count() {
  timeout "$PROBE_SECS" candump -T "$((PROBE_SECS * 1000))" "$IFACE" 2>/dev/null | wc -l
}

probe_one() {
  local name="$1" kind="$2" nominal="$3" data="$4" why="$5"
  printf '  %-12s %-38s ' "$name" "$why"
  if ! configure "$kind" "$nominal" "$data"; then
    printf '\033[90munsupported by firmware\033[0m\n'
    return 1
  fi
  local n state
  n="$(frame_count)"
  state="$(can_state)"
  if (( n > 0 )); then
    printf '\033[32m%d frames\033[0m  [%s]\n' "$n" "${state:-?}"
    return 0
  fi
  printf '\033[33msilent\033[0m       [%s]\n' "${state:-?}"
  return 1
}

# --- forced single config -----------------------------------------------------
if [[ $# -ge 1 ]]; then
  for c in "${CONFIGS[@]}"; do
    read -r name kind nominal data why <<<"$c"
    if [[ "$name" == "$1" ]]; then
      configure "$kind" "$nominal" "$data" || die "could not apply $name"
      info "$IFACE up: $name (listen-only)"
      ip -details link show "$IFACE"
      exit 0
    fi
  done
  die "unknown config '$1'"
fi

# --- probe --------------------------------------------------------------------
info "Probing $IFACE, ${PROBE_SECS}s per config, listen-only throughout."
echo "Ignition ON, engine off. Modules sleep after a few idle minutes -- if"
echo "everything reads silent, cycle the ignition and run again."
echo

WINNER=""
for c in "${CONFIGS[@]}"; do
  read -r name kind nominal data why <<<"$c"
  if probe_one "$name" "$kind" "$nominal" "$data" "$why"; then
    WINNER="$name"
    break
  fi
done

echo
if [[ -n "$WINNER" ]]; then
  for c in "${CONFIGS[@]}"; do
    read -r name kind nominal data why <<<"$c"
    [[ "$name" == "$WINNER" ]] && configure "$kind" "$nominal" "$data"
  done
  info "Traffic found: $WINNER. $IFACE left up in that config (listen-only)."
  echo "Next: ./capture.sh baseline"
  exit 0
fi

link_down
cat <<'MSG'
No traffic on any candidate config.

Distinguish the two explanations before going further:

  ERROR-WARNING / ERROR-PASSIVE during a probe
      Traffic IS present, timing is wrong. Widen the config list.

  ERROR-ACTIVE and zero frames on every config
      The bus is genuinely quiet at this connector. On a 2024 car the
      likely cause is a gateway that filters broadcast traffic out of the
      OBD-II port and only passes diagnostic request/response.
      Confirm: bring the interface up WITHOUT listen-only, send a request
      to 0x7DF, and watch for a 0x7E8 reply. A reply with no other traffic
      means the port is gatewayed and the real bus must be tapped upstream.
MSG
exit 1
