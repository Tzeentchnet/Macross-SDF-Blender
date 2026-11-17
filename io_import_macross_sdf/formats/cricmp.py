"""CRI ``CRICMP`` decompressor.

Clean-room Python port of the token-level behaviour documented by the LGPL
``zeesworth/cricmp`` decoder (see docs/formats/cricmp.md).

Stream layout (after the 0x20-byte header, data at header[0x18] or 0x20)::

    u16  ignored
    u32  BE block count (version >= 2.0; u16 for older streams)
    block[count]:  u16 BE flags, 16 x u16 BE tokens
    u8   trailing-byte correction, u8 tail token count
    tail block: u16 flags + tail tokens

Token with flag bit set: two literal bytes.  Flag clear:
  * ``code & 0xF000 == 0`` -> repeat previous byte ``code + 3`` times
  * otherwise -> copy ``(code >> 12) + 2`` bytes from ``out - (code & 0xFFF)``
"""

from __future__ import annotations

import struct

MAGIC = b"CRICMP"


def is_cricmp(data: bytes) -> bool:
    return data[:6] == MAGIC


def decompress(data: bytes) -> bytes:
    if not is_cricmp(data):
        raise ValueError("not a CRICMP stream")
    try:
        version = float(data[8:16].split(b"\0")[0].decode("ascii") or "1.0")
    except ValueError:
        version = 1.0
    out_size = struct.unpack_from("<I", data, 0x14)[0]
    start = struct.unpack_from("<I", data, 0x18)[0] or struct.unpack_from("<I", data, 0x10)[0] or 0x20
    out = bytearray(out_size)
    o = 0
    end = out_size  # exclusive
    p = start + 2
    if version >= 2.0:
        nblocks = struct.unpack_from(">I", data, p)[0]
        p += 4
    else:
        nblocks = struct.unpack_from(">H", data, p)[0]
        p += 2

    mv = data  # local alias

    def block(p, o, ntok):
        flags = (mv[p] << 8) | mv[p + 1]
        p += 2
        for i in range(ntok):
            if o >= end:
                return p, o, -1
            hi = mv[p]
            lo = mv[p + 1]
            p += 2
            if flags & (1 << i):
                if o == end - 1:
                    out[o] = hi
                    return p, o + 1, 1
                out[o] = hi
                out[o + 1] = lo
                o += 2
            else:
                code = (hi << 8) | lo
                remaining = end - o
                if code & 0xF000 == 0:
                    n = min(code + 3, remaining)
                    b = out[o - 1]
                    out[o:o + n] = bytes((b,)) * n
                else:
                    n = min((code >> 12) + 2, remaining)
                    src = o - (code & 0x0FFF)
                    if src + n <= o:
                        out[o:o + n] = out[src:src + n]
                    else:  # overlapping copy, byte by byte
                        for k in range(n):
                            out[o + k] = out[src + k]
                o += n
        return p, o, 0

    result = 0
    for _ in range(nblocks):
        p, o, r = block(p, o, 16)
        # NOTE: the reference decoder's ``result = f() < 0`` stores a boolean.
        result = 1 if r < 0 else 0
        if r < 0:
            return bytes(out)
    if p + 2 <= len(mv):
        code_hi, code_lo = mv[p], mv[p + 1]
        p += 2
        if code_lo > 0:
            p, o, r = block(p, o, code_lo)
            result = 1 if r < 0 else 0
    return bytes(out)


def maybe_decompress(data: bytes) -> bytes:
    return decompress(data) if is_cricmp(data) else data
