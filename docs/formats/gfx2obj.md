# GFX2OBJ models (`GFX2OBJ/PS2;0100` and `;0200`)

Code: [`formats/gfx2obj.py`](../../io_import_macross_sdf/formats/gfx2obj.py),
[`formats/vif.py`](../../io_import_macross_sdf/formats/vif.py).

Confidence: **confirmed**.

- All 7,989 model leaves on the disc parse: 7,668 `0100` and 321 `0200`.
- All 18,896 node meshes decode into one of five layouts.
- Hierarchy and transform order were taken from the engine (`gfxSetObjSub`) and checked visually against complete VF-1, Glaug, Regult and stage assemblies.

## Header

| off | type | meaning |
|---|---|---|
| 0x00 | char[16] | `GFX2OBJ/PS2;0100` or `;0200` |
| 0x10 | u32 | texture-name table offset |
| 0x14 | u32 | material table offset |
| 0x18 | u32 | node table offset |
| 0x1C | u32 | packet (VIF) region offset (`P`) |

Each table is padded to 16 bytes.

### Texture names

`u32 count`, then `count × 32` bytes. Each record is `char name[30]` followed
by a `u16` id. The name matches a `tex.lst` entry without `.tm2`. The match
is case-insensitive; the id's meaning is unknown.

### Materials

`u32 count`, then `count × 36` bytes, read as 9 × u32:

| word | meaning |
|---|---|
| 0 | low u16 = **kind**: 2 = opaque, 1 = translucent (canopies, FX). High u16 is 3 in every sample (unknown). |
| 1–3 | unknown blend/test words (`0x000D0000`, `0x00000301`, `0x0101FF20` / `0x0101FE44` ...). Kept as a custom property. |
| 4–7 | `umin, umax, vmin, vmax`: the texel rectangle the material's UVs cover. Probably used for partial texture uploads; it is not a clamp. |
| 8 | texture index into the name table |

## Nodes

**0100**: the table holds `u32 count`, then `count × 48`-byte records:

| off | type | meaning |
|---|---|---|
| 0x00 | f32[3] | translation |
| 0x0C | f32[3] | rotation (radians) |
| 0x18 | f32[3] | scale |
| 0x24 | i32 | mesh offset relative to `P` (−1 = none) |
| 0x28 | i32 | material index |
| 0x2C | i16 | first child (−1 = none) |
| 0x2E | i16 | next sibling (−1 = none) |

`0100` models carry no node names.

**0200**: a 0x20-byte table header with the count at +0x1C, then
`count × 176`-byte records:

| off | type | meaning |
|---|---|---|
| 0x00 | u32 | 0 (unknown) |
| 0x04 | u32 | node-name offset relative to `P`. The NUL-terminated strings follow the last packet. |
| 0x08 | u32 | 0 (unknown) |
| 0x0C | f32[3] ×3 | T, R, S |
| 0x30 | i32 | mesh offset relative to `P` |
| 0x34 | i32 | material |
| 0x38 | i32 | first child |
| 0x3C | i32 | next sibling |
| 0x40–0xAF | | always zero on disc (runtime work area) |

**Transform** (from `gfxSetObjSub`, which calls `gfxTransMatrix`,
`gfxRotZMatrix`, `gfxRotYMatrix`, `gfxRotXMatrix` and `gfxScaleMatrix` in that
order):

```
M_local = T · Rz · Ry · Rx · S          (column vectors)
M_world = M_parent · M_local
```

Game space is **right-handed, +Y up**. Characters face −Z, fighters fly
toward +Z, and 1 unit is about 1 m: a VF-1 Battroid is about 10.4 units tall.

## Mesh packets

`P + mesh_offset` points to a DMA tag. The low 16 bits are the QWC, and the
ID is 6 (`ret`). The tag's upper 64 bits are two VIF `NOP`s, followed by
`QWC` quadwords of VIF code. The commands that occur are:

```
UNPACK V3-32 @0  num 3      info block (9 words)
[UNPACK V3-32 @0 ...]       vertex pool, indexed meshes only (pos/normal pairs);
                            >256 qwords are split into chunks at addr 0x000, 0x100, 0x200
repeat per batch:
  UNPACK V4-8  @0 (TOPS, unsigned) num 3   three RGBA8 material colours
  UNPACK V4-32 or V3-32 @3 (TOPS)          batch header + vertices
  MSCNT                                   run the VU1 program
```

### Info block (9 × u32)

| word | meaning |
|---|---|
| 0–5 | bounds (centre/extent-like floats; not needed for import) |
| 6 | radius |
| 7 | **format flags**: bit0 UV, bit1 vertex colour, bit2 normal, bit4 unknown (VE-1 dome, some event meshes) |
| 8 | direct meshes: batch count. Indexed meshes: `(batches << 16) \| pool_vertex_count` |

### Batch header (first qword of the @3 unpack)

`(f32 specular_power, u32 flags, u32 vertex_count, 0)`.

- Specular power: observed 50.0, 9.0, and 0 (no specular).
- Flags: 0, 2, 8 or 10 observed. Bit 3 coincides with `colors[0]` being white, so it is treated as emissive/unlit.

### Vertex layouts (all observed)

| flags | unpack | stride | per-vertex data | count |
|---|---|---|---|---|
| 0x5 | V4-32 | 2 qw | `(x y z u) (nx ny nz v)` | 12,499 meshes |
| 0x15 | V4-32 | 2 qw | same as 0x5 | 161 |
| 0x3 | V3-32 | 2 × vec3 | `(x y z) (u v rgba8-packed-in-float-bits)` (prelit) | 2,857 |
| 0x4 | V3-32 | 1 × vec3 | `(index, u, v)`; the index points into the pool of `(pos, normal)` pairs | 3,378 |
| 0x2 | V3-32 | 1 × vec3 | `(index, u, v)`; pool second vec3 carries colour | 1 |

UVs are normalised to the whole texture, with v measured from the top. In
prelit (0x3) meshes the vertex colour is RGBA8, where 0x80 means 1.0.

### Material colours (V4-8 block)

There are three RGBA8 colours per batch:

- `colors[0]`: emission (black, or white on unlit batches)
- `colors[1]`: diffuse (`FFFFFF`, `B2B2B2` ...)
- `colors[2]`: specular

Prelit meshes have all three set to zero.

### Topology

**One triangle strip per batch.** There are no restart flags; degenerate
triangles occur and are dropped. Batches hold at most 62 vertices.

The GS has no back-face culling, so strip parity is **not** consistent: about
25 % of batches start with the opposite winding. The importer orients every
triangle so that its geometric normal agrees with the summed vertex normals.
Prelit meshes have no normals and keep strip parity.

## Not yet understood

- Material words 1–3 (alpha test/blend/ZBUF settings). The node `+0x00` and `+0x08` words in `0200`.
- Flag bit 4 (0x15 meshes).
- The bound/radius words in the info block. These are not required.
- How the hard-point model (`h00_hard_0.mdl`) and the `wp_efct*` / `ep_efct*` / `p_act*` locator nodes are used at runtime. These are effect, weapon and actuator attach points; they are imported as bones.
