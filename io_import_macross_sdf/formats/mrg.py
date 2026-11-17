"""MRG offset-table archives (magic-less) and recursive asset-tree helpers.

Layout::

    u32 count
    u32 header_size (== start of member 0)
    u32 offsets[count-1] (starts of members 1..count-1)
    ... padding up to header_size

Member 0 is very often an ASCII list (``mrg.lst``, ``mdl.lst``, ``mot.lst``,
``tex.lst``) whose first line names the list itself and whose following lines
name members 1..N-1.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


def parse(data: bytes, max_count: int = 4096) -> list[bytes] | None:
    """Return member slices or None if ``data`` is not a plausible MRG."""
    n = len(data)
    if n < 16:
        return None
    count, hdr = struct.unpack_from("<II", data, 0)
    if not (1 <= count <= max_count) or hdr % 16 or hdr < 8 + 4 * (count - 1) or hdr > n:
        return None
    starts = [hdr] + list(struct.unpack_from(f"<{count - 1}I", data, 8)) if count > 1 else [hdr]
    for a, b in zip(starts, starts[1:]):
        if b <= a or b % 16 or b > n:
            return None
    return [data[s:(starts[i + 1] if i + 1 < count else n)] for i, s in enumerate(starts)]


def parse_list(data: bytes) -> list[str] | None:
    """Decode an ASCII manifest member, or None if it is not one."""
    end = data.find(b"\0")
    raw = data if end < 0 else data[:end]
    if not raw or len(raw) > 65536:
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    if any(c not in "\r\n\t" and not (32 <= ord(c) < 127) for c in text):
        return None
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    if not lines or not lines[0].strip().lower().endswith(".lst"):
        return None
    while lines and lines[-1] == "":
        lines.pop()
    return lines


# --------------------------------------------------------------------------
# Typed leaf detection

def sniff(data: bytes) -> str:
    if data[:7] == b"GFX2OBJ":
        return "gfx2obj"
    if data[:4] == b"TIM2":
        return "tim2"
    if data[:6] == b"CRICMP":
        return "cricmp"
    if data[:4] == b"AUTH":
        return "auth"
    if data[:4] == b"MRGA":
        return "mrga"
    if data[:3] == b"CLS":
        return "collision"
    if data[:12] == b"GFX2GMOT0300":
        return "gmot"
    if len(data) >= 4 and struct.unpack_from("<H", data, 0)[0] == 0x3B71:
        return "bon" if struct.unpack_from("<H", data, 2)[0] == 1 else "mot"
    if parse_list(data) is not None:
        return "list"
    if parse(data) is not None:
        return "mrg"
    return "raw"


@dataclass
class Node:
    name: str
    kind: str
    data: bytes
    children: list["Node"] = field(default_factory=list)
    path: str = ""

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def find_all(self, kind: str):
        return [n for n in self.walk() if n.kind == kind]


def build_tree(data: bytes, name: str = "root", path: str = "", depth: int = 0) -> Node:
    """Recursively expand MRG containers into a Node tree, naming members
    from list manifests where available."""
    from . import cricmp

    if cricmp.is_cricmp(data):
        data = cricmp.decompress(data)
    kind = sniff(data)
    node = Node(name, kind, data, path=path or name)
    if kind != "mrg" or depth > 8:
        return node
    members = parse(data)
    names = None
    if members and sniff(members[0]) == "list":
        names = parse_list(members[0])
    for i, m in enumerate(members):
        if names and i < len(names) and names[i] not in ("", "_"):
            cname = names[i]
        elif names and i < len(names) and names[i] == "_":
            cname = f"_{i}"
        else:
            cname = f"{i:03d}"
        # Leaf types never contain nested MRGs; avoid false-positive MRG parses
        child = build_tree(m, cname, f"{node.path}/{cname}", depth + 1)
        node.children.append(child)
    return node


def dump_tree(node: Node, indent: int = 0, out=None) -> str:
    lines = [] if out is None else out
    lines.append("  " * indent + f"{node.name} [{node.kind}] {len(node.data)} bytes")
    for c in node.children:
        dump_tree(c, indent + 1, lines)
    return "\n".join(lines)
