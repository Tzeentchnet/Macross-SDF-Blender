# Blender importer design

The add-on lives in [`io_import_macross_sdf/`](../io_import_macross_sdf) and
is a Blender 5.x extension (`blender_manifest.toml`).

```
formats/   no bpy - iso, cricmp, mrg, vif, gfx2obj, gs, tim2, motion, pose, stage, assets
blender/   bpy adapter - mathutil (numpy matrices), build (meshes/materials/rigs/actions),
           importer (bundle -> scene orchestration)
_addon.py  operators, preferences, menu entries
```

## Operators (File › Import)

| entry | operator | use |
|---|---|---|
| Macross SDF Asset (.cmp/.mrg) | `import_scene.macross_sdf_file` | an extracted archive or decompressed `.bin`. Shared skeletons come from the disc path in Preferences, when set. |
| Macross SDF from Disc Image | `import_scene.macross_sdf_disc` | choose any archive inside the ISO, including `BIN.CVM/…`. Offers the colour variants of a craft. |
| Macross SDF Motions onto Rig | `import_scene.macross_sdf_motions` | adds every compatible clip of an archive (`MOT_*`, `AUTH_*`, `*_AC`) to the active imported armature |

Options:

- LODs: highest or all. Lower LODs go into hidden collections.
- Hierarchy: Auto, Armature or Baked.
- Motions on/off, and shared skeletons/motions from the disc.
- Scale.
- Texture filter.
- Stage pattern blocks (1 or 3 …) and stage pattern index.
- Weld strip vertices.

## Coordinate conversion

Game space is right-handed with +Y up. Blender space is right-handed with +Z up.

```
blender = C · game,  C = [[-1,0,0],[0,0,1],[0,1,0]]      (proper rotation)
vertices: C · W_node · v        bone/object matrices: C · M · C⁻¹
```

Characters face −Y (Blender front view). Fighters fly toward +Y, because the
game's fighter nose points to +Z. Scale is 1 game unit = 1 Blender unit
(≈ 1 m).

## Meshes

Per model file, all node meshes are merged into **one mesh object**:

- Vertices are welded per node by exact position, so strips become connected.
- Faces are oriented with the vertex normals.
- Game normals are set as custom split normals (`normals_split_custom_set`).
- UVs: `v' = 1 − v`.
- Two FLOAT_COLOR corner attributes:
  - `gfx_color`: batch diffuse colour for lit meshes, vertex colour / 128 for prelit meshes
  - `gfx_emit`: batch emission colour

All arrays are written with `foreach_set` from numpy.

## Materials

Materials are shared per bundle, keyed by (texture, GFX2 material kind, lit).

- **Lit:** Principled BSDF.
  - Base = texture × `gfx_color`.
  - Emission = texture × `gfx_emit`.
  - Alpha = texture alpha × vertex alpha.
  - Roughness from the Phong exponent: `sqrt(2/(n+2))`.
- **Prelit/unlit** (stage scenery, sky, FX): Emission shader, mixed with Transparent by alpha.
- **Blending:**
  - Kind 1, or `_TRA_` textures, with alpha → *Blended*.
  - Otherwise → *Dithered* (alpha-tested look).
  - Back-face culling is off, as on the GS.

The raw material words are kept in custom properties for research.

## Rigs and animation

Every model node becomes a bone. The bone matrix is the node's world matrix
in Blender space with scale removed. The mesh uses rigid 1.0 vertex groups
per node plus an Armature modifier. Bones store `gfx_node_index` and the
node's rest T/R/S.

Clips are evaluated by `formats/pose.py`, which reproduces the game's FK +
IK including the IK chains (see [formats/motion.md](formats/motion.md)).
Evaluation produces per-frame local matrices. For each bone:

```
M_pose  = W_anim · W_rest⁻¹ · B_rest          (armature space)
basis   = B_rest⁻¹ · B_parent_rest · M_parent⁻¹ · M_pose
```

The basis is decomposed into location, quaternion and scale, keyed every
frame (LINEAR interpolation, 60 fps). Keys go into a **slotted action**
(Blender 4.4+/5.x API: `action.slots`,
`anim_utils.action_ensure_channelbag_for_slot`). Each clip gets its own NLA
track (muted). The first clip is active, and actions keep a fake user.

Baked per-frame keys are used instead of copying the game curves because
bone rest orientations differ from the game's node frames and because IK
results are not curve data.

## Stages

Static models are baked once; each distinct model becomes one mesh
datablock. Ground tiles and arranged objects are **linked duplicates**:
objects that share mesh data, with `matrix_world = C · M · C⁻¹`. GD_01, for
example, produces 195 objects from 58 meshes.

## Performance

| asset | import time |
|---|---|
| VF-1J bundle (3 models, 2 rigs, ~70 clips with IK) | ~1.6 s |
| Macross City stage | ~0.6 s |

Whole-disc smoke import (569 archives): see `E:\tests\macross_sdf\smoke_all.json`.
