"""Stage (``GD_xx.CMP``) layout tables.

A stage archive is an MRG whose ``mrg.lst`` names its members::

    gd_NNmdl.mrg     models: gbtm (sea/bottom plane), gfixed (fixed scenery),
                     gsky/gskyPS (sky dome), GV_nn_{L,M,S} ground tiles,
                     OBJ_nn_{l,m,s} placeable objects (buildings ...)
    gd_NNtex.tex     TIM2 textures (MRG with tex.lst)
    gd_NNcls.mrg     collision (optional)
    GRD_Param.bin    "GRDPARAM 0.520" - fog, light, clip and grid settings
    GRD_ObjArr.mrg   object arrangements (optional)
    GRD_PatTbl.mrg   pattern tables

GRD_PatTbl members:
    last member : u32 pattern_count, u32 side   (side x side cells)
    before that : pattern_count ObjArr grids (only if GRD_ObjArr exists),
                  then pattern_count ground-tile grids.
    Each grid is side*side u16 (row-major), 1-based; 0 = empty.
    ObjArr grid values index GRD_ObjArr members, tile grid values select
    GV_nn_<lod>_0.mdl.  Several patterns are alternative layouts of the same
    stage (GRD_GetPat / GRD_GetCrntPat select one at runtime).
GRD_ObjArr members: u32 count, count x {u32 obj_id, f32 T[3], f32 R[3], f32 S[3]}
    obj_id n refers to OBJ_nn_<lod>_0.mdl; positions are local to the cell.

The game draws the pattern block repeatedly (3x3 blocks around the camera,
see ``grd_PatTableInit``).  Cells are 400 x 400 units (observed).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field


@dataclass
class Placement:
    obj_id: int
    translation: tuple
    rotation: tuple
    scale: tuple


@dataclass
class StageLayout:
    side: int = 0
    cell_size: float = 400.0
    pattern_count: int = 0
    tile_grids: list[list[int]] = field(default_factory=list)
    arr_grids: list[list[int]] = field(default_factory=list)
    arrangements: list[list[Placement]] = field(default_factory=list)
    param_raw: bytes = b""

    def tile_grid(self, pattern: int = 0) -> list[int]:
        return self.tile_grids[pattern] if pattern < len(self.tile_grids) else []

    def arr_grid(self, pattern: int = 0) -> list[int]:
        return self.arr_grids[pattern] if pattern < len(self.arr_grids) else []


def parse_pattern(members: list[bytes], has_objarr: bool):
    """Return (pattern_count, side, tile_grids, arr_grids)."""
    if not members or len(members[-1]) < 8:
        return 0, 0, [], []
    count, side = struct.unpack_from("<II", members[-1], 0)
    if not (0 < side <= 64) or not (0 < count <= 16):
        return 0, 0, [], []
    grids = []
    for m in members[:-1]:
        n = side * side
        if len(m) < 2 * n:
            grids.append(list(struct.unpack_from(f"<{len(m) // 2}H", m, 0)) + [0] * (n - len(m) // 2))
        else:
            grids.append(list(struct.unpack_from(f"<{n}H", m, 0)))
    if has_objarr and len(grids) >= 2 * count:
        arr, tiles = grids[:count], grids[count:2 * count]
    else:
        arr, tiles = [], grids[:count]
    return count, side, tiles, arr


def parse_arrangement(data: bytes) -> list[Placement]:
    if len(data) < 4:
        return []
    n = struct.unpack_from("<I", data, 0)[0]
    out = []
    for i in range(n):
        r = 4 + 40 * i
        if r + 40 > len(data):
            break
        oid = struct.unpack_from("<I", data, r)[0]
        v = struct.unpack_from("<9f", data, r + 4)
        out.append(Placement(oid, v[0:3], v[3:6], v[6:9]))
    return out
