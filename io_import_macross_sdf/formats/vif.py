"""Minimal PS2 VIF1 command-stream walker.

Only what is needed to recover GFX2 model batches is implemented: commands
are decoded with their payload sizes, UNPACK payloads are expanded to numpy
arrays (honouring signed/unsigned and STCYCL write-skipping is ignored because
the observed streams always use CL == WL).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

CMD_NAMES = {
    0x00: "NOP", 0x01: "STCYCL", 0x02: "OFFSET", 0x03: "BASE", 0x04: "ITOP",
    0x05: "STMOD", 0x06: "MSKPATH3", 0x07: "MARK", 0x10: "FLUSHE", 0x11: "FLUSH",
    0x13: "FLUSHA", 0x14: "MSCAL", 0x15: "MSCALF", 0x17: "MSCNT", 0x20: "STMASK",
    0x30: "STROW", 0x31: "STCOL", 0x4A: "MPG", 0x50: "DIRECT", 0x51: "DIRECTHL",
}


@dataclass
class VifCmd:
    offset: int        # byte offset of the command word in the source buffer
    cmd: int           # command with interrupt bit stripped
    num: int
    imm: int
    payload: bytes = b""

    @property
    def is_unpack(self) -> bool:
        return self.cmd >= 0x60

    @property
    def vn(self) -> int:
        return (self.cmd >> 2) & 3

    @property
    def vl(self) -> int:
        return self.cmd & 3

    @property
    def addr(self) -> int:
        return self.imm & 0x3FF

    @property
    def unsigned(self) -> bool:
        return bool(self.imm & 0x4000)

    @property
    def tops(self) -> bool:
        return bool(self.imm & 0x8000)

    @property
    def masked(self) -> bool:
        return bool(self.cmd & 0x10)

    @property
    def fmt(self) -> str:
        if not self.is_unpack:
            return CMD_NAMES.get(self.cmd, f"CMD{self.cmd:02X}")
        if self.vl == 3:
            return "V4-5"
        return f"{'S' if self.vn == 0 else 'V%d' % (self.vn + 1)}-{32 >> self.vl}"

    def unpack(self) -> np.ndarray:
        """Return the UNPACK payload as an (num, components) array."""
        n = self.num or 256
        comps = self.vn + 1
        if self.vl == 3:  # V4-5: RGBA5551 in a u16
            v = np.frombuffer(self.payload, "<u2", n)
            return np.stack([(v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3,
                             (v >> 15) << 7], axis=1).astype(np.uint32)
        bits = 32 >> self.vl
        if bits == 32:
            # keep raw words; callers reinterpret as float or int
            return np.frombuffer(self.payload, "<u4", n * comps).reshape(n, comps)
        dt = {16: "u2", 8: "u1"}[bits]
        if not self.unsigned:
            dt = dt.replace("u", "i")
        return np.frombuffer(self.payload, "<" + dt, n * comps).reshape(n, comps)


def unpack_bytes(cmd: int, num: int) -> int:
    vn = (cmd >> 2) & 3
    vl = cmd & 3
    n = num or 256
    if vl == 3:
        bits = 16
    else:
        bits = (32 >> vl) * (vn + 1)
    total = (bits * n + 31) // 32 * 4
    return total


def walk(data: bytes, start: int, end: int):
    """Yield VifCmd objects for the VIF stream in data[start:end]."""
    p = start
    while p + 4 <= end:
        w = struct.unpack_from("<I", data, p)[0]
        cmd = (w >> 24) & 0x7F
        num = (w >> 16) & 0xFF
        imm = w & 0xFFFF
        off = p
        p += 4
        size = 0
        if cmd >= 0x60:
            size = unpack_bytes(cmd, num)
        elif cmd == 0x20:
            size = 4
        elif cmd in (0x30, 0x31):
            size = 16
        elif cmd == 0x4A:
            size = (num or 256) * 8
        elif cmd in (0x50, 0x51):
            size = (imm or 65536) * 16
            # DIRECT payload is qword aligned
            if p % 16:
                p += 16 - p % 16
        payload = data[p:p + size]
        p += size
        yield VifCmd(off, cmd, num, imm, payload)
