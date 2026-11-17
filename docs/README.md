# Macross SDF (PS2) asset research

These notes are for people writing tools for *Chou Jikuu Yousai Macross*
(PS2, Japan, `SLPM-65405`, Sega AM2 "GFX2" engine). Every format described
here is implemented in the Blender-free
[`io_import_macross_sdf/formats`](../io_import_macross_sdf/formats) package,
which can be used directly from Python.

| document | content |
|---|---|
| [findings.md](findings.md) | research log: how each result was obtained, validation status |
| [issues.md](issues.md) | open questions, unimplemented features, uncertain interpretations |
| [asset-catalogue.md](asset-catalogue.md) | what is on the disc, by file family, with counts |
| [formats/containers.md](formats/containers.md) | ISO/CVM, CRICMP, MRG, list manifests, leaf identification |
| [formats/gfx2obj.md](formats/gfx2obj.md) | models: header, materials, node tree, VIF packets, vertex layouts, strips |
| [formats/tim2.md](formats/tim2.md) | textures: TIM2 header, CLUT, GS swizzle (PSMCT32 → PSMT8/4) |
| [formats/motion.md](formats/motion.md) | `.bon` skeletons, `.mot` clips, key encoding, sign flips, IK solver |
| [formats/stage.md](formats/stage.md) | `GD_xx` stages: ground tiles, pattern tables, object arrangements |
| [blender-importer.md](blender-importer.md) | how parsed data maps to Blender 5.2 (meshes, materials, rigs, actions) |
| [testing.md](testing.md) | tools, headless tests, where the verification renders are |

Engine symbols referenced in these documents (`gfxSetObjSub`,
`am2mMotionCalcChain` …) come from the symbol table in the game's main ELF;
addresses are for `SLPM_654.05`. The SDF_Macross recomp's
`docs/file-formats.md` and `docs/engine.md` hold the earlier container
research this work builds on.

No game data is stored in this repository.
