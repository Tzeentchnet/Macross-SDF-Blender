# Disc, CVM, CRICMP and MRG containers

Game: *Chou Jikuu Yousai Macross* (PS2, Japan, `SLPM-65405`).
Code: [`formats/iso.py`](../../io_import_macross_sdf/formats/iso.py),
[`formats/cricmp.py`](../../io_import_macross_sdf/formats/cricmp.py),
[`formats/mrg.py`](../../io_import_macross_sdf/formats/mrg.py).

Confidence: **confirmed**. Every archive on the disc parses, and the
CRICMP port's output is byte-identical to the reference `cricmp.exe`.

## Disc → CVM

The disc is plain ISO 9660 (2,048-byte sectors). Each `*.CVM` is a CRI ROFS
container: a `CVMH` header, then a complete ISO 9660 image starting at
**+0x1800**. Both levels are read with the same directory walker. The
SDF_Macross recomp docs (`docs/file-formats.md`) list every root file.
`ETC.CVM` has no embedded volume.

`GameDisc` gives each file a path such as `BIN.CVM/VF1J_AC.CMP`. It also
accepts a folder of files that were already extracted.

## CRICMP (`*.CMP`)

```
0x00 "CRICMP\0\0"   0x08 version "2.10"   0x10 u32 header size (0x20)
0x14 u32 decompressed size                0x18 u32 data offset (0x20)
data: u16 (ignored), u32 BE block count (u16 if version < 2.0)
      block = u16 BE flag word + 16 tokens (u16 BE each)
      tail  = u8 correction, u8 token count, partial block
```

Each token is one of three kinds:

- **Flag bit set:** two literal bytes.
- **Flag bit clear, `code & 0xF000 == 0`:** repeat the previous byte `code + 3` times.
- **Otherwise:** copy `(code >> 12) + 2` bytes from `out - (code & 0xFFF)`. The source may overlap the destination.

The pure-Python decoder takes about 50 ms per MB.

## MRG (magic-less offset table)

```
u32 count, u32 offset_of_member0 (= header size), u32 offsets[count-1]
```

Offsets are 16-byte aligned and strictly increasing. A member ends where the
next one starts, so member slices include alignment padding. MRG nests
freely: decompressed `.CMP` files, `.MSD`, `.CAT`, `.CHRW`, `.AUT`, `.TEX`
and stage sub-archives are all MRG.

### List manifests

Member 0 is usually an ASCII list with CRLF line endings. Its first line
names the list itself, and that line may have trailing spaces, for example
`"mrg.lst "`. Line *i* names member *i*. `_` marks an unnamed member. The
known list types are:

| first line | meaning |
|---|---|
| `mdl.lst` | GFX2OBJ models (`*.mdl`) |
| `tex.lst` | TIM2 textures (`*.tm2`) |
| `mot.lst` | one `.bon` skeleton (optional) + `.mot` clips |
| `mrg.lst` | stage/top-level sub-archives (`gd_NNmdl.mrg`, `GRD_Param.bin` ...) |
| `auth.lst` / `data.lst` | event (AUTH) bundles |
| `lgt.lst`, `se.lst` | event lights / sound effects |

### Leaf identification (`mrg.sniff`)

| leaf | how it is identified |
|---|---|
| `GFX2OBJ/PS2;0100` / `;0200` | model ([gfx2obj.md](gfx2obj.md)) |
| `TIM2` | texture ([tim2.md](tim2.md)) |
| u16 `0x3B71` + u16 kind | `.bon` (kind 1) / `.mot` (kind 0) ([motion.md](motion.md)) |
| `CLS COLLISION LIBLARY VER 1.00` | collision (not decoded) |
| `AUTH` | event script (not decoded) |
| `MRGA` | menu authoring data (not decoded) |
| `GRDPARAM 0.520` | stage parameters ([stage.md](stage.md)) |

## Typical bundles

```
VF1J_AC.CMP (player craft)            ENM_GLG.CMP (enemy)
 ├ 000 mdl.lst  b00_lod_l_f_0.mdl      ├ 000 models (b00_lod_l, b01_lod_m, b02_lod_s)
 │              b01_lod_l_b_0.mdl      ├ 001 textures
 │              b02/b03 (LOD m), b04   ├ 002 collision (CLS)
 │              h00_hard_0.mdl         └ (motions live in MOT_GLAUG.MRG)
 ├ 001 mot.lst  T00_Transf_FG.mot, T01_Transf_GB.mot
 └ 002 tex.lst  cano_00, vf1j_opa_000, vf1j_tra_000
```

`_l_`, `_m_` and `_s_` are levels of detail. `_f_` is the fighter/Gerwalk
model and `_b_` is the Battroid model. `h00_hard` holds the hard-point
markers.
