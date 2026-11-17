# Stages / maps (`GD_xx.CMP`)

Code: [`formats/stage.py`](../../io_import_macross_sdf/formats/stage.py),
[`blender/importer.py`](../../io_import_macross_sdf/blender/importer.py)
(`import_stage`).

Confidence:

- Archive layout, ObjArr records and PatTbl framing: **confirmed**. They parse on all 39 stages.
- Cell placement (row-major, 400-unit cells centred on the origin): **corroborated visually**. Roads and rivers continue across tile borders in `GD_01`.
- Mapping from stage to mission: **unknown**.

## Archive

`GD_xx.CMP` decompresses to an MRG whose `mrg.lst` names the members:

| member | content |
|---|---|
| `gd_NNmdl.mrg` | models (see below) |
| `gd_NNtex.tex` | TIM2 textures (MRG + `tex.lst`) |
| `gd_NNcls.mrg` | collision (`CLS COLLISION LIBLARY`) – optional, not decoded |
| `GRD_Param.bin` | `GRDPARAM 0.520`: fog colours/ranges, light colours, far clip, cloud layers … (kept raw) |
| `GRD_ObjArr.mrg` | object arrangements – optional |
| `GRD_PatTbl.mrg` | ground pattern tables |

Model name prefixes:

| prefix | meaning |
|---|---|
| `gbtm` | bottom plane: ocean surface, sea floor, 100 km square |
| `gfixed` | fixed scenery: distant city, islands, fleet; up to ±19,200 units |
| `gsky`, `gskyPS` | sky dome: unlit, prelit, ~52 km radius |
| `GV_nn_{L,M,S}_0` | ground tiles, 400 × 400 units, three LODs |
| `OBJ_nn_{l,m,s}_0` | placeable objects (buildings) |
| `SP_nn`, `BSP_nn` | special/background set pieces, e.g. SDF-1, Earth, planets. **Placement unknown**; imported at their own origin |
| `gmov` | moving ground, e.g. asteroid fields |

## `GRD_ObjArr`

Each member is one arrangement:

```
u32 count
count × { u32 obj_id, f32 T[3], f32 R[3], f32 S[3] }     (40 bytes)
```

`obj_id = n` selects `OBJ_nn_<lod>_0.mdl`, 1-based. Transforms are local to
the cell and use the same `T·Rz·Ry·Rx·S` convention as model nodes.

## `GRD_PatTbl`

```
last member:  u32 pattern_count, u32 side
before it:    [pattern_count ObjArr grids  — only when GRD_ObjArr exists]
              pattern_count ground-tile grids
grid:         side*side u16, row-major, 1-based (0 = empty)
```

Examples:

| stage | patterns | side | notes |
|---|---|---|---|
| GD_00 | 2 | 4 | pattern 0 = unique tiles 1–16; pattern 1 = mostly open-sea tile 4 |
| GD_01 | 1 | 6 | Macross City; 32 arrangements |
| GD_08 | 1 | 6 | tiles 1–36 |
| GD_13 | 1 | 16 | sparse interior (ship hangar?) |

The trailing u32 of grid members looked like a byte count on GD_01 but holds
garbage elsewhere; ignore it.

### Placement

The importer centres cell `(row r, col c)` at
`x = (c - (side-1)/2) * 400` and `z = (r - (side-1)/2) * 400` in game space.
`grd_PatTableInit` fills a 3×3 neighbourhood
(`GRD_GetPat(i, j)`, i ∈ −1…1, j ∈ 1…−1) at multiples of a cell-size global.
This means the game repeats the pattern block around the camera; set
**Stage pattern blocks = 3** to reproduce it.

The 400-unit cell size was observed from tile bounds (±200). The runtime
global at `gp-0x6458` was not read.

## Stage catalogue (observations from model/texture names)

| stage | content |
|---|---|
| GD_00, GD_21 | ocean, Macross Island, UN fleet (`kantai`), SDF-1 set piece |
| GD_01, GD_22 | Macross City (grid of buildings) |
| GD_02, GD_04, GD_10, GD_23, GD_25 | space near Earth / SDF-1 (`earthmap`, `moon`, `galaxy`) |
| GD_03 | ocean + fleet + SDF-1 |
| GD_06, GD_27 | asteroid field / Saturn ring (`inseki`, `saturn`) |
| GD_07, GD_16 | space battle (Zentradi fleet, `houdai`) |
| GD_08, GD_09, GD_29–GD_33 | atmosphere / cloud layers above ground |
| GD_11, GD_19, GD_20, GD_35 | ruined Earth, Zentradi armada (`m_ruinearthmap`) |
| GD_13, GD_28 | ship interior / hangar (`container`, `iriguti`, `computer`) |
| GD_14, GD_15, GD_38, GD_46, GD_47 | sea (`fsea`), sea floor (`umisoko`) |
| GD_18, GD_26 | city blocks (close-up `bl_*` buildings) |
| GD_34, GD_36, GD_37 | small special sets (Earth/Boddole?) |
| GD_48, GD_49 | tutorial (`tut`) |

Stages are referenced from mission data (`MCRS*.MSD`, `MIS_*PH*.MRG`), which
is not decoded yet.
