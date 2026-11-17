"""ISO 9660 and CRI CVM (ROFS) readers.

The game disc is a plain ISO 9660 image.  Its ``*.CVM`` files are CRI CVM
containers: a ``CVMH`` header followed (at +0x1800) by a second, embedded
ISO 9660 image.  Both levels are read with the same directory walker.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

SECTOR = 0x800
CVM_ISO_BASE = 0x1800


@dataclass
class IsoEntry:
    name: str
    offset: int  # absolute byte offset in the underlying file
    size: int
    is_dir: bool = False


class IsoReader:
    """Reads an ISO 9660 image located at ``base`` inside ``path``."""

    def __init__(self, path: str, base: int = 0, fh=None):
        self.path = path
        self.base = base
        self._fh = fh or open(path, "rb")
        self._own = fh is None
        self.entries: dict[str, IsoEntry] = {}
        self._read_volume()

    def close(self):
        if self._own:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _read(self, off: int, size: int) -> bytes:
        self._fh.seek(off)
        return self._fh.read(size)

    def _read_volume(self):
        pvd = self._read(self.base + 16 * SECTOR, SECTOR)
        if pvd[1:6] != b"CD001":
            raise ValueError(f"no ISO 9660 PVD at base 0x{self.base:X} in {self.path}")
        root = pvd[156:156 + 34]
        lba, size = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
        self._walk(lba, size, "")

    def _walk(self, lba: int, size: int, prefix: str, depth: int = 0):
        if depth > 16:
            return
        data = self._read(self.base + lba * SECTOR, size)
        pos = 0
        while pos < len(data):
            rec_len = data[pos]
            if rec_len == 0:  # pad to next sector
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            rec = data[pos:pos + rec_len]
            pos += rec_len
            e_lba = struct.unpack_from("<I", rec, 2)[0]
            e_size = struct.unpack_from("<I", rec, 10)[0]
            flags = rec[25]
            nlen = rec[32]
            raw = rec[33:33 + nlen]
            if raw in (b"\x00", b"\x01"):
                continue
            name = raw.decode("ascii", "replace").split(";")[0]
            full = prefix + name
            is_dir = bool(flags & 2)
            self.entries[full.upper()] = IsoEntry(full, self.base + e_lba * SECTOR, e_size, is_dir)
            if is_dir:
                self._walk(e_lba, e_size, full + "/", depth + 1)

    def files(self) -> list[IsoEntry]:
        return [e for e in self.entries.values() if not e.is_dir]

    def find(self, name: str) -> IsoEntry | None:
        return self.entries.get(name.upper())

    def read(self, name_or_entry) -> bytes:
        e = name_or_entry if isinstance(name_or_entry, IsoEntry) else self.find(name_or_entry)
        if e is None:
            raise KeyError(name_or_entry)
        return self._read(e.offset, e.size)


class GameDisc:
    """Unified access to every file on the disc, including files inside CVMs.

    Paths are addressed as ``"BIN.CVM/VF1J_AC.CMP"`` or ``"CRSDAT.MRG"``.
    A folder of already-extracted files can be used instead of the ISO.
    """

    def __init__(self, path: str):
        self.path = path
        self.iso: IsoReader | None = None
        self.cvms: dict[str, IsoReader] = {}
        self.folder: str | None = None
        if os.path.isdir(path):
            self.folder = path
        else:
            self.iso = IsoReader(path)
            for e in self.iso.files():
                if e.name.upper().endswith(".CVM"):
                    try:
                        self.cvms[e.name.upper()] = IsoReader(path, e.offset + CVM_ISO_BASE, fh=self.iso._fh)
                    except ValueError:
                        pass  # ETC.CVM is an all-zero placeholder

    def close(self):
        if self.iso:
            self.iso.close()

    def list(self) -> list[str]:
        if self.folder:
            out = []
            for root, _dirs, files in os.walk(self.folder):
                for f in files:
                    out.append(os.path.relpath(os.path.join(root, f), self.folder).replace("\\", "/"))
            return sorted(out)
        out = [e.name for e in self.iso.files()]
        for cname, cvm in self.cvms.items():
            out += [f"{cname}/{e.name}" for e in cvm.files()]
        return sorted(out)

    def read(self, path: str) -> bytes:
        if self.folder:
            p = os.path.join(self.folder, path)
            if not os.path.exists(p):  # allow flat folders: try the bare file name
                p = os.path.join(self.folder, path.split("/")[-1])
            with open(p, "rb") as fh:
                return fh.read()
        parts = path.replace("\\", "/").split("/", 1)
        if len(parts) == 2 and parts[0].upper() in self.cvms:
            return self.cvms[parts[0].upper()].read(parts[1])
        return self.iso.read(path)
