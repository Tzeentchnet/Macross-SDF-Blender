"""TIM2 texture decoder (numpy).

Observed on this disc: image types 4 (4-bit indexed) and 5 (8-bit indexed),
CLUT type 3 (32-bit RGBA, CSM1) and rarely 1 (16-bit), optional mipmaps.
Pixel data is GS-swizzled when file byte 0x0A == 0xFF (see gs.py), otherwise
linear.  8-bit CSM1 palettes use the
standard PS2 block permutation (entries 8..15 swapped with 16..23 in every
32-entry group).  PS2 alpha 0x80 means fully opaque.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from . import gs


@dataclass
class Picture:
    width: int
    height: int
    image_type: int
    clut_type: int
    mipmaps: int
    rgba: np.ndarray            # (h, w, 4) uint8, row 0 = top
    tex0: int = 0
    tex1: int = 0
    gs_regs: int = 0
    gs_texclut: int = 0
    raw_alpha_max: int = 0      # max alpha byte before expansion (diagnostic)
    swizzled: bool = False


def _expand_alpha(a: np.ndarray) -> np.ndarray:
    return np.minimum(a.astype(np.uint16) * 255 // 128, 255).astype(np.uint8)


def _clut(data: bytes, off: int, size: int, ctype: int, count: int) -> np.ndarray:
    base = ctype & 0x3F
    if base == 3:  # 32-bit
        pal = np.frombuffer(data, np.uint8, count * 4, off).reshape(count, 4).copy()
    elif base == 2:  # 24-bit
        pal = np.frombuffer(data, np.uint8, count * 3, off).reshape(count, 3)
        pal = np.concatenate([pal, np.full((count, 1), 0x80, np.uint8)], 1)
    elif base == 1:  # 16-bit RGBA5551
        v = np.frombuffer(data, "<u2", count, off).astype(np.uint32)
        pal = np.stack([(v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3,
                        np.where(v >> 15, 0x80, 0)], 1).astype(np.uint8)
    else:
        raise ValueError(f"unsupported CLUT type {ctype:#x}")
    csm2 = bool(ctype & 0x80)
    if count == 256 and not csm2:
        idx = np.arange(256)
        blk = (idx & 0x18)
        perm = (idx & ~0x18) | ((blk == 8) * 16 + (blk == 16) * 8 + (blk == 0) * 0 + (blk == 24) * 24)
        pal = pal[perm]
    return pal


def parse(data: bytes) -> list[Picture]:
    if data[:4] != b"TIM2":
        raise ValueError("not TIM2")
    align = data[5]
    count = struct.unpack_from("<H", data, 6)[0]
    # Game-specific: byte 0x0A == 0xFF marks GS-swizzled (PSMCT32-uploaded) pixels.
    swizzled = data[0x0A] == 0xFF
    p = 0x80 if align else 0x10
    out = []
    for _ in range(count):
        (total, clut_size, img_size, hdr_size, clut_colors, pfmt, mips, ctype, itype,
         w, h) = struct.unpack_from("<IIIHHBBBBHH", data, p)
        tex0, tex1 = struct.unpack_from("<QQ", data, p + 0x18)
        regs, texclut = struct.unpack_from("<II", data, p + 0x28)
        img_off = p + hdr_size
        clut_off = img_off + img_size
        n = w * h
        idx = None
        if itype in (4, 5) and swizzled:
            idx = gs.unswizzle(data[img_off:img_off + n * (8 if itype == 5 else 4) // 8], w, h,
                               8 if itype == 5 else 4)
        if idx is not None:
            pass
        elif itype == 5:
            idx = np.frombuffer(data, np.uint8, n, img_off)
        elif itype == 4:
            b = np.frombuffer(data, np.uint8, (n + 1) // 2, img_off)
            idx = np.empty(b.size * 2, np.uint8)
            idx[0::2] = b & 0x0F
            idx[1::2] = b >> 4
            idx = idx[:n]
        elif itype == 3:
            px = np.frombuffer(data, np.uint8, n * 4, img_off).reshape(h, w, 4).copy()
            raw_a = int(px[..., 3].max()) if n else 0
            px[..., 3] = _expand_alpha(px[..., 3])
            out.append(Picture(w, h, itype, ctype, mips, px, tex0, tex1, regs, texclut, raw_a))
            p += total
            continue
        elif itype == 2:
            px = np.frombuffer(data, np.uint8, n * 3, img_off).reshape(h, w, 3)
            px = np.concatenate([px, np.full((h, w, 1), 255, np.uint8)], 2)
            out.append(Picture(w, h, itype, ctype, mips, px, tex0, tex1, regs, texclut, 0x80))
            p += total
            continue
        else:
            raise ValueError(f"unsupported TIM2 image type {itype}")
        pal = _clut(data, clut_off, clut_size, ctype, clut_colors)
        raw_a = int(pal[:, 3].max()) if len(pal) else 0
        pal = pal.copy()
        pal[:, 3] = _expand_alpha(pal[:, 3])
        rgba = pal[np.minimum(idx, len(pal) - 1)].reshape(h, w, 4)
        out.append(Picture(w, h, itype, ctype, mips, rgba, tex0, tex1, regs, texclut, raw_a, swizzled))
        p += total
    return out


def to_png(pic: Picture, path: str):
    """Write a Picture as PNG using only zlib (no PIL dependency)."""
    import zlib

    raw = b"".join(b"\0" + pic.rgba[y].tobytes() for y in range(pic.height))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", pic.width, pic.height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)
