"""Parser for candump log format (`candump -L` / `candump -l`).

Handles classic and CAN FD frames, standard and extended IDs:

    (1748188800.123456) can0 1A2#DEADBEEF          classic
    (1748188800.123456) can0 1A2##1DEADBEEF        CAN FD, flags nibble = 1
    (1748188800.123456) can0 18DAF110#0210         extended (29-bit) ID
    (1748188800.123456) can0 123#R8                remote frame
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_LINE = re.compile(
    r"^\((?P<ts>\d+\.\d+)\)\s+(?P<iface>\S+)\s+(?P<id>[0-9A-Fa-f]+)(?P<sep>##?)(?P<rest>\S*)\s*$"
)


@dataclass(frozen=True)
class Frame:
    ts: float
    iface: str
    can_id: int
    data: bytes
    extended: bool
    fd: bool
    remote: bool = False

    @property
    def id_hex(self) -> str:
        return f"{self.can_id:08X}" if self.extended else f"{self.can_id:03X}"


def parse_line(line: str) -> Frame | None:
    m = _LINE.match(line.strip())
    if not m:
        return None

    id_str = m.group("id")
    # candump prints 29-bit IDs as 8 hex chars, 11-bit as 3.
    extended = len(id_str) == 8
    can_id = int(id_str, 16)
    fd = m.group("sep") == "##"
    rest = m.group("rest")

    if rest[:1] in ("R", "r"):
        return Frame(float(m.group("ts")), m.group("iface"), can_id, b"", extended, fd, True)

    if fd:
        rest = rest[1:]  # strip the FD flags nibble

    if len(rest) % 2:
        return None
    try:
        data = bytes.fromhex(rest)
    except ValueError:
        return None

    return Frame(float(m.group("ts")), m.group("iface"), can_id, data, extended, fd)


def read_log(path: str | Path) -> Iterator[Frame]:
    """Yield frames from a candump log, skipping unparseable lines."""
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            frame = parse_line(line)
            if frame is not None:
                yield frame
