# Known issues and open questions

Most important first.

## Not implemented / not decoded

1. **Bone constraints (`dy_*`, `tform_*` lists B/C).**
   - The lists are evaluated by callback tables at 0x385B20 / 0x385AC0 in `am2mMotionCalcMatrix`.
   - Observed types: `(6,0,joint)` on elbow covers, `(9,0,chain_root)` and `(3,)` on shoulder covers, `(1,)` on thigh covers, `(3,0)` on `tform_sune_*`.
   - Without them, cover parts keep FK/rest orientation: small visual differences around elbows, shoulders and thighs on IK rigs.
   - Next step: disassemble the callbacks.
2. **AUTH event scripts** (`AUTH` blocks inside `*.aut`, `EVT_*.AUT`, `SCENE1.AUT`).
   - Header: `AUTH`, size, version 1/2, `f32 60.0`, data offset 0x2C. `ANIM`, camera and actor tracks follow.
   - Event set models and textures import. Event clips can be applied to a craft rig with *Motions onto Rig*.
   - Camera/actor placement and timing are not decoded.
3. **Mission data** (`MCRS*.MSD`, `MIS_*PH*.MRG` `_enm/_gen/_abs.pos/_rel/_stg.bin`, `CAMPATH*`). Enemy placement, and which `GD_xx` belongs to which mission, are unknown.
4. **`SP_*` / `BSP_*` stage set pieces** (SDF-1, Earth …) import at their model origin. Their placement probably comes from mission data.
5. **Collision** (`CLS COLLISION LIBLARY VER 1.00`, 725 leaves). Only the signature and the recomp's header notes are known; not imported.
6. **`GRD_Param.bin`** (fog, light colours, clip distances) is kept raw. Fog and world colours are not applied to the Blender world.
7. **UV/texture animation** (`AMM_StartChangeTexture`, `auth_ObjUVAnimSetModel*`) and **effect particles** are not handled. FX meshes import statically.
8. **Effector offset tables** (runtime flags 0x08000000–0x80000000 in `am2mMotionCalcChain`) are treated as zero.

## Uncertain interpretations

- **Material words 1–3** and **GFX2 kind** semantics. Kind 1 is assumed translucent. Blend modes are approximated as Blended/Dithered.
- **`colors[0]` as emission** and batch flag bit 3 as unlit. These are consistent with the data but not proven from VU1 microcode, which is uploaded at runtime and not in the ELF.
- **Vertex colours of prelit meshes:** byte order RGBA with 0x80 = 1.0 is assumed. The alpha byte is often 0xFF, so alpha is clamped to 1.
- **Specular:** the Phong exponent → roughness conversion is an approximation.
- **Stage cell orientation** (rows along +Z). It is visually consistent on GD_01, but the cell-size global (`gp-0x6458`) was not read at runtime.
- **Scale channels:** the game evaluates scale only when node flag bit 1, or a global flag, is set. The importer always applies scale tracks; these are used, for example, to hide parts during transformations.
- **Shoulder twist** handling (`j_kata_*`, RotY(−twist) on the elbow) follows the disassembly literally. Arms reach their targets with ≈ 0.07–0.2 units of error. This may be faithful, or a misread of `gfxRotYMatrix`'s argument.

## Cosmetic / tooling

- Some FX/briefing models reference textures that live in another archive (`MInseki_many_02`, `Mback_star02` …). They import untextured, with a console warning.
- Clips in archives without a `mot.lst` get numeric names (`002`, `003` …), e.g. `ENM_RGN`.
- EEVEE logs "Shadow buffer full" on very large stages. Harmless; test renders disable sun shadows for stages.
