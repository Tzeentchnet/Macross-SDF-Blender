"""GFX2OBJ model parser (versions 0100 and 0200).

See docs/formats/gfx2obj.md for the full write-up.  Summary::

    0x00 char[16] "GFX2OBJ/PS2;0100" | "GFX2OBJ/PS2;0200"
    0x10 u32 texture-name table offset
    0x14 u32 material table offset
    0x18 u32 node table offset
    0x1C u32 packet (VIF) region offset

    texture table : u32 count, count x {char name[30]; u16 id}
    material table: u32 count, count x 36 bytes (tex index at +0x20)
    node table 0100: u32 count, count x 48-byte nodes
    node table 0200: 0x20-byte header (count at +0x1C), count x 176-byte nodes

Each node with ``mesh >= 0`` points (packet-relative) at a DMA ``ret`` tag
whose QWC covers a VIF stream: a 3-qword info block (UNPACK V3-32 @0), an
optional shared vertex pool (UNPACK V3-32 @0) and then batches of
``V4-8 @0`` (3 material colours) + ``V4-32/V3-32 @3`` (header + strip).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from . import vif

FLAG_UV = 0x1
FLAG_COLOR = 0x2
FLAG_NORMAL = 0x4
FLAG_10 = 0x10  # observed on VE-1 / some event meshes; meaning unknown


@dataclass
class Material:
    index: int
    texture: int          # index into Model.textures (-1 = none)
    raw: tuple            # 9 raw u32 for diagnostics
    uv_region: tuple      # (umin, umax, vmin, vmax) texel rectangle used
    kind: int             # first u16: 1/2 observed


@dataclass
class Batch:
    start: int            # first triangle index in Mesh.faces
    count: int
    colors: np.ndarray    # (3,4) uint8 material colours: [emission?, diffuse, specular]
    spec_power: float
    flags: int            # batch header word 1 (0,2,8,10 observed)


@dataclass
class Mesh:
    fmt: int
    indexed: bool
    positions: np.ndarray          # (n,3) float32, game space
    normals: np.ndarray | None     # (n,3)
    uvs: np.ndarray | None         # (n,2)  (v measured from the top of the texture)
    colors: np.ndarray | None      # (n,4) uint8 vertex colours (prelit meshes)
    faces: np.ndarray              # (m,3) int32 into positions
    face_batch: np.ndarray         # (m,) int32 batch index per face
    batches: list[Batch] = field(default_factory=list)
    info: tuple = ()               # raw 9-word info block


@dataclass
class Node:
    index: int
    name: str
    translation: tuple
    rotation: tuple                # radians, applied X then Y then Z (M = T Rz Ry Rx S)
    scale: tuple
    mesh_offset: int
    material: int
    child: int
    sibling: int
    parent: int = -1
    mesh: Mesh | None = None


@dataclass
class Model:
    version: str
    textures: list[str]
    texture_ids: list[int]
    materials: list[Material]
    nodes: list[Node]
    warnings: list[str] = field(default_factory=list)

    def roots(self):
        return [n for n in self.nodes if n.parent < 0]


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("ascii", "replace")


def parse(data: bytes, decode_meshes: bool = True) -> Model:
    sig = data[:16]
    if not sig.startswith(b"GFX2OBJ/PS2;"):
        raise ValueError("not a GFX2OBJ model")
    version = sig[12:16].decode()
    o_tex, o_mat, o_node, o_pk = struct.unpack_from("<4I", data, 16)

    ntex = struct.unpack_from("<I", data, o_tex)[0]
    textures, tex_ids = [], []
    for i in range(ntex):
        r = o_tex + 4 + 32 * i
        textures.append(_cstr(data[r:r + 30]))
        tex_ids.append(struct.unpack_from("<H", data, r + 30)[0])

    nmat = struct.unpack_from("<I", data, o_mat)[0]
    materials = []
    for i in range(nmat):
        w = struct.unpack_from("<9I", data, o_mat + 4 + 36 * i)
        kind = w[0] & 0xFFFF
        tex = w[8] if w[8] < ntex else -1
        materials.append(Material(i, tex, w, (w[4], w[5], w[6], w[7]), kind))

    nodes = []
    if version == "0200":
        count = struct.unpack_from("<I", data, o_node + 0x1C)[0]
        for i in range(count):
            r = o_node + 0x20 + i * 0xB0
            name_off = struct.unpack_from("<I", data, r + 4)[0]
            t = struct.unpack_from("<3f", data, r + 0x0C)
            ro = struct.unpack_from("<3f", data, r + 0x18)
            s = struct.unpack_from("<3f", data, r + 0x24)
            mesh, mat, child, sib = struct.unpack_from("<4i", data, r + 0x30)
            name = _cstr(data[o_pk + name_off:o_pk + name_off + 64]) if o_pk + name_off < len(data) else ""
            nodes.append(Node(i, name, t, ro, s, mesh, mat, child, sib))
    else:
        count = struct.unpack_from("<I", data, o_node)[0]
        for i in range(count):
            r = o_node + 4 + i * 48
            t = struct.unpack_from("<3f", data, r)
            ro = struct.unpack_from("<3f", data, r + 0x0C)
            s = struct.unpack_from("<3f", data, r + 0x18)
            mesh, mat = struct.unpack_from("<2i", data, r + 0x24)
            child, sib = struct.unpack_from("<2h", data, r + 0x2C)
            nodes.append(Node(i, f"node_{i:03d}", t, ro, s, mesh, mat, child, sib))

    model = Model(version, textures, tex_ids, materials, nodes)

    # parent links from first-child / next-sibling
    for n in nodes:
        c = n.child
        guard = 0
        while 0 <= c < len(nodes) and guard < len(nodes):
            nodes[c].parent = n.index
            c = nodes[c].sibling
            guard += 1

    if decode_meshes:
        for n in nodes:
            if n.mesh_offset >= 0:
                try:
                    n.mesh = decode_mesh(data, o_pk + n.mesh_offset)
                except Exception as e:  # keep importing other nodes
                    model.warnings.append(f"node {n.index} ({n.name}): {e}")
    return model


def _strip_faces(idx: np.ndarray) -> np.ndarray:
    """Triangles of a strip with alternating winding; degenerates removed."""
    n = len(idx)
    if n < 3:
        return np.zeros((0, 3), np.int32)
    a = idx[:-2]
    b = idx[1:-1]
    c = idx[2:]
    odd = (np.arange(n - 2) & 1).astype(bool)
    f = np.stack([a, np.where(odd, c, b), np.where(odd, b, c)], 1)
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    return f[keep].astype(np.int32)


def decode_mesh(data: bytes, p: int) -> Mesh:
    tag = struct.unpack_from("<I", data, p)[0]
    qwc = tag & 0xFFFF
    end = min(len(data), p + 16 + qwc * 16)
    cmds = list(vif.walk(data, p + 8, end))

    info = None
    pool = None
    pool_q = None
    cur_colors = np.zeros((3, 4), np.uint8)
    pos_l, nrm_l, uv_l, col_l, face_l, fb_l = [], [], [], [], [], []
    batches = []
    base = 0
    fmt = 0
    indexed = False
    for c in cmds:
        if not c.is_unpack:
            continue
        if not c.tops and c.fmt == "V3-32":
            if info is None and c.num == 3 and c.addr == 0:
                info = struct.unpack("<9I", c.payload[:36])
                fmt = info[7]
                indexed = (info[8] >> 16) != 0
            else:
                # Shared vertex pool; >256 qwords are split into chunks at
                # qword addresses 0x000, 0x100, 0x200 ...
                chunk = c.unpack().view("<f4")
                need = c.addr + len(chunk)
                if pool_q is None:
                    pool_q = np.zeros((need, 3), np.float32)
                elif len(pool_q) < need:
                    pool_q = np.concatenate([pool_q, np.zeros((need - len(pool_q), 3), np.float32)])
                pool_q[c.addr:need] = chunk
                pool = pool_q[:len(pool_q) // 2 * 2].reshape(-1, 2, 3)
            continue
        if c.addr == 0 and c.tops and c.fmt == "V4-8":
            cur_colors = np.asarray(c.unpack(), np.uint8).reshape(3, 4)
            continue
        if c.addr == 3 and c.tops and c.fmt in ("V4-32", "V3-32"):
            a = c.unpack()
            hdr = a[0]
            n = int(hdr[2])
            body = a[1:]
            if n <= 0:
                continue
            if c.fmt == "V4-32" and len(body) >= 2 * n:
                f = body[:2 * n].view("<f4").reshape(n, 8)
                pos_l.append(f[:, 0:3])
                nrm_l.append(f[:, 4:7])
                uv_l.append(np.stack([f[:, 3], f[:, 7]], 1))
                col_l.append(None)
                vidx = np.arange(base, base + n)
                base += n
            elif c.fmt == "V3-32" and len(body) >= 2 * n and not indexed:
                raw = body[:2 * n].reshape(n, 6)
                f = raw.view("<f4")
                pos_l.append(f[:, 0:3])
                if fmt & FLAG_NORMAL:
                    nrm_l.append(f[:, 3:6])
                    uv_l.append(None)
                    col_l.append(None)
                else:
                    nrm_l.append(None)
                    uv_l.append(f[:, 3:5] if fmt & FLAG_UV else None)
                    col_l.append(raw[:, 5].astype("<u4").view(np.uint8).reshape(n, 4)
                                 if fmt & FLAG_COLOR else None)
                vidx = np.arange(base, base + n)
                base += n
            elif c.fmt == "V3-32" and len(body) >= n and indexed and pool is not None:
                raw = body[:n]
                pi = raw[:, 0].astype(np.int64)
                if pi.max(initial=0) >= len(pool):
                    raise ValueError("vertex index outside pool")
                f = raw.view("<f4")
                pos_l.append(pool[pi, 0])
                if fmt & FLAG_NORMAL:
                    nrm_l.append(pool[pi, 1])
                    col_l.append(None)
                else:
                    nrm_l.append(None)
                    col_l.append(pool[pi, 1].view("<u4")[:, 2].view(np.uint8).reshape(-1, 4)
                                 if fmt & FLAG_COLOR else None)
                uv_l.append(f[:, 1:3])
                vidx = np.arange(base, base + n)
                base += n
            else:
                continue
            faces = _strip_faces(vidx)
            bi = len(batches)
            batches.append(Batch(sum(len(x) for x in face_l), len(faces), cur_colors.copy(),
                                 float(np.frombuffer(struct.pack("<I", int(hdr[0])), "<f4")[0]),
                                 int(hdr[1])))
            face_l.append(faces)
            fb_l.append(np.full(len(faces), bi, np.int32))

    if not pos_l:
        return Mesh(fmt, indexed, np.zeros((0, 3), np.float32), None, None, None,
                    np.zeros((0, 3), np.int32), np.zeros(0, np.int32), [], info or ())
    positions = np.concatenate(pos_l).astype(np.float32)

    def cat(lst, width, dtype, fill):
        if all(x is None for x in lst):
            return None
        return np.concatenate([x if x is not None else np.full((len(p_), width), fill, dtype)
                               for x, p_ in zip(lst, pos_l)]).astype(dtype)

    normals = cat(nrm_l, 3, np.float32, 0.0)
    uvs = cat(uv_l, 2, np.float32, 0.0)
    colors = cat(col_l, 4, np.uint8, 0x80)
    faces = np.concatenate(face_l) if face_l else np.zeros((0, 3), np.int32)
    face_batch = np.concatenate(fb_l) if fb_l else np.zeros(0, np.int32)

    # The GS has no back-face culling, so strip parity is not meaningful.
    # Orient every triangle to agree with its vertex normals when available.
    if normals is not None and len(faces):
        v = positions[faces]
        fn = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        vn = normals[faces].sum(1)
        flip = np.einsum("ij,ij->i", fn, vn) < 0
        faces[flip] = faces[flip][:, [0, 2, 1]]
    return Mesh(fmt, indexed, positions, normals, uvs, colors, faces, face_batch, batches, info or ())
