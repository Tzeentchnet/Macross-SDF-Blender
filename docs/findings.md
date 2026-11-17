# Research log and key findings

This file records how each result was obtained, so others can re-check it.
The starting point was the SDF_Macross recomp's `docs/file-formats.md`, which
had the container framing and partial GFX2OBJ/TIM2/MOT notes. Tools used:

- Python + numpy surveys over all 569 archives (`tools/survey_disc.py`)
- the recomp's `tools/disasm_elf.py` (Capstone) on `SLPM_654.05`, which has its full symbol table
- [`tools/disasm_vu0.py`](../tools/disasm_vu0.py), which decodes VU0 macro (COP2) words the Capstone wrapper leaves as `.word`
- headless Blender renders (`tools/blender_test_import.py`, `tools/render_pose.py`) for visual checks

## Timeline of decisive observations

1. **Node record layouts.** In `0200` nodes, the u32 values at +0x04 increase
   in small steps. They are offsets of NUL-terminated names stored after the
   last packet, relative to the packet region. The ints at +0x38/+0x3C form a
   first-child/next-sibling tree. In `0100` nodes the same pair is two
   **i16** values at +0x2C/+0x2E. `gfxSetObjSub` confirms this: it reads
   `lh 0x2c` / `lh 0x2e` and the mesh/material at +0x24/+0x28.

2. **Mesh offsets.** Each mesh offset points to a DMA `ret` tag. Its QWC
   equals the distance to the next node's mesh, and node 3's offset 0x3FF0
   equals (0x3FE + 1) × 16.

3. **Vertex layouts.** A survey of 18,896 meshes showed only five unpack
   signatures. The info block's word 7 is a flag set: UV, colour and normal
   bits. Its word 8 packs `(batches << 16) | pool_size` when the mesh is
   indexed. Indexed batches carry integer pool indices in the x lane. Some
   pools exceed 256 qwords and are split over unpacks at VU addresses
   0x000/0x100/0x200.

4. **Strip winding.** About 75 % of strip triangles agree with the vertex
   normals and 25 % do not, with a constant parity per batch. The GS does not
   cull back faces, so the data never needed a consistent winding; orienting
   triangles by their normals is safe.

5. **TIM2 swizzle.** Raw palette lookups showed vertical streaks.
   - File byte 0x0A = 0xFF marks swizzled textures. Only 22 tiny textures have 0x00.
   - The "unswizzle8" formula fixed square 8-bit textures but failed on non-square 4-bit ones.
   - A GS memory emulation (PSMCT32 write, then PSMT8/PSMT4 read) handles every size. It matches the formula bit-for-bit where the formula is valid.

6. **Axes.** Comparing world-space feet and head of the Battroid gave Y-up.
   Mirrored "U.N.SPACY" decals under a mirroring conversion showed the game
   is right-handed. Characters face −Z, and the fighter's nose node is at +Z.

7. **Motion keys.**
   - First guesses (bfloat16, 3-bit types, linear default) produced wild IK targets.
   - `am2mFcurveDecode16` shows 2-bit key types, flat tangents for value-only keys, and `half` floats decoded as `((h & 0x7FFF) << 13) + 0x38000000`.
   - `AM2M_FcurveCalc` is plain Hermite. With slopes per second (÷ fps), the median overshoot dropped from 650 % to 0.

8. **Sign flips.** `am2mMotionCalcMatrix` multiplies the rx, ry and tz curve
   results by −1. Statistics confirm it: over thousands of constant tracks,
   rx/ry/tz equal −rest and rz/tx/ty equal rest.

9. **Channel stream order.** Wide-entry clips matched the skeleton only
   53 % of the time in bit order and 96.5 % with T→R→S group order. Narrow
   clips are almost all single-group, so they are unaffected.

10. **IK.**
    - `_am2mMotionCalc` jumps on node type 0–4, and these values are the low 16 bits of the `.bon` flags.
    - Chain roots (type 2) call `am2mMotionCalcChain`. That function aims at the effector target with RotZ·RotY, then applies the law of cosines with a bend side taken from the second joint's flag. `j_kata_l/r` get a twist removal; the strings are at 0x3C2678/0x3C2688.
    - Effectors use their constant (rest) translation, so they sit at the chain end.
    - IK is active whenever the effector has any translation track.
    - With these rules the solved feet land exactly on their targets.

## Validation status

| item | status |
|---|---|
| containers, CRICMP, MRG | all 569 archives |
| GFX2OBJ parse + mesh decode | 7,989 / 7,989, no warnings |
| TIM2 decode | 2,997 / 2,997 |
| `.bon` / `.mot` parse | 28 / 28, 469 / 469 (footer check) |
| Blender smoke import | 569 archives, see `E:\tests\macross_sdf\smoke_all.json` |
| visual | VF-1J fighter/Gerwalk/Battroid + transformation, VE-1, VF-1J liveries, Glaug, Regult, Macross City, Macross Island/ocean, FX, AUTH clips on VF-1J |
