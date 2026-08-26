# Crosstrek CAN bus tooling

Monitoring and reverse-engineering tools for a **2024 Subaru Crosstrek**
(third generation, Subaru "D" harness, angle-based LKAS) using **CANable 2.0**
adapters over SocketCAN.

Everything here is **read-only**. Nothing in this directory transmits on a
vehicle bus.

## Requirements

- `can-utils` (`candump`, `cansniffer`, `cangen`)
- CANable 2.0 on candleLight firmware, so it appears as a native SocketCAN
  interface via `gs_usb`. An FD-capable firmware build is needed for the CAN FD
  probe; stock candleLight images are not always FD-capable.
- `pip install -r requirements.txt` for the Python tools.

## Workflow

### 1. Find the bit timing

```bash
./bringup.sh
```

Probes classic 500k, CAN FD 500k/2M and 500k/5M, then 125k and 250k, six
seconds each, listen-only throughout. Leaves the interface up in whichever
config saw traffic.

Ignition on, engine off. Modules sleep after a few idle minutes; if every
config reads silent, cycle the ignition and re-run.

Reading the result:

| Observation | Meaning |
|---|---|
| Frames on `classic500` | Ordinary powertrain bus. Proceed. |
| Frames on an `fd*` config | CAN FD bus. Proceed; all tools handle FD. |
| `ERROR-WARNING` / `ERROR-PASSIVE`, zero frames | Traffic present, timing wrong. Widen the config list. |
| `ERROR-ACTIVE`, zero frames everywhere | Bus genuinely quiet at this connector — likely a gateway. See below. |

### 2. Rule out a gateway

If the port is silent on every config, the 2024-model-year explanation is a
gateway that filters broadcast traffic out of the OBD-II connector and passes
only diagnostic request/response.

Confirm by bringing the interface up **without** `listen-only`, sending a
request to `0x7DF`, and watching for a `0x7E8` reply. A reply with no other
traffic means the port is gatewayed and the real bus has to be tapped upstream,
behind the driver's kick panel at the body integrated unit.

This outcome determines the scope of everything downstream, so establish it
before investing in captures.

### 3. Capture

```bash
./capture.sh baseline -t 60                      # touch nothing
./capture.sh avh-button -t 60 -n "pressed x8"    # one control, repeatedly
```

Writes `logs/<label>-<timestamp>.log` in candump log format plus a `.meta`
sidecar recording the interface config, so a driveway capture stays
interpretable later.

### 4. Find the frame

```bash
tools/event_diff.py logs/baseline-*.log logs/avh-button-*.log
```

Reports bit positions that took a value in the event capture never seen in the
baseline, ranked cleanest-change-first. A discrete control is usually one or
two bits on one ID. Bytes that were already noisy at rest — rolling counters,
checksums, continuous sensors — are demoted rather than reported as signal.

Nothing this tool prints is a result until it reproduces. Re-run both captures,
watch the candidate live with `cansniffer -c can0`, and capture the inverse
action to confirm the bit clears.

### 5. Decode what is already known

```bash
tools/decode.py --dbc path/to/subaru_*.dbc logs/baseline-*.log
```

Prints ID and frame coverage before decoding anything, because **no DBC is
known to fit the 2024 Crosstrek exactly**. The 2018–2023 Global Platform files
in [opendbc](https://github.com/commaai/opendbc) are a starting hint, not
ground truth — the third-gen car is a separate port.

Watch for the length-mismatch warning. Matched IDs that disagree on DLC are the
signature of a DBC from a different year, and any signal decoded from them is
garbage that looks plausible.

Check opendbc master for a newer generated Subaru file before assuming the 2017
one is the best available.

## Layout

```
bringup.sh          bit-timing probe, brings interface up listen-only
capture.sh          named capture with metadata sidecar
tools/canlog.py     candump log parser (classic + FD, 11- and 29-bit IDs)
tools/event_diff.py isolate the frame behind a control input
tools/decode.py     DBC coverage report and signal decode
logs/               captures land here (git-ignored)
```

## Planned: auto-enable a driver-assist feature at startup

The intended follow-on is having a feature that resets every drive cycle turn
itself on at ignition — replaying the button-press frame identified in step 4.

**That step transmits on a vehicle bus and is not staged here.** The capture
work above is a prerequisite for it either way, and is worth completing on its
own before any transmit path is designed.

Before writing anything to the bus, these need answers:

- Which bus carries the button, and is the target module actually listening on
  the segment reachable from the tap point?
- Does the frame need a rolling counter or checksum to be accepted? Most
  modern chassis frames do, and a stale counter is silently ignored at best.
- What does the real button do that a replayed frame does not — does a module
  arbitrate the request against vehicle state?
- What happens on conflict, when both the replay and the physical button assert?

On a 2024 car the angle-based-LKAS and EyeSight 4 messaging is still being
worked out by the community, and there is no rollback for a module that latches
a fault. Read-only until each question above has a tested answer.
