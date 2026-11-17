# Tools and testing

All commands run from the repository root. `ISO` is the path to
`Chou Jikuu Yousai Macross (Japan).iso`, and `BLENDER` is
`D:/Blender Foundation/Blender 5.2/blender.exe`.

## Blender-free

| tool | purpose |
|---|---|
| `python tools/survey_disc.py ISO [--json out.json]` | parse every archive, model, texture and clip; print coverage and failures (~40 s) |
| `python tools/disasm_vu0.py <recomp>/tools/disasm_elf.py <ELF> <symbol>` | disassemble a function with VU0 macro instructions decoded |
| `python tools/contact_sheet.py out.png a.png b.png …` | labelled contact sheet of renders (Pillow) |

The `formats` package is plain Python + numpy:

```python
from io_import_macross_sdf.formats import iso, assets, pose
disc = iso.GameDisc(ISO)
b = assets.load_bundle(disc.read("BIN.CVM/VF1J_AC.CMP"), "VF1J_AC.CMP")
model = b.models[0].model          # nodes, materials, meshes (numpy)
pic = b.picture("VF1J_OPA_000")    # decoded RGBA texture
```

## Headless Blender

| tool | purpose |
|---|---|
| `BLENDER -b --factory-startup --python tools/blender_test_import.py -- --iso ISO --out DIR [opts] ASSET…` | import assets, save `DIR/<name>.blend`, render previews, update `DIR/report.json` |
| `BLENDER -b --factory-startup --python tools/blender_smoke_all.py -- --iso ISO --out report.json [--filter GD_]` | import every archive without saving; report failures |
| `BLENDER -b FILE.blend --python tools/render_pose.py -- --rig NAME --action NAME --frame N --out PREFIX` | orthographic top/side/front/persp renders of one pose |

`blender_test_import.py` options:

| option | effect |
|---|---|
| `--views persp,front,side,top,back` | camera angles |
| `--actions a,b` | which clips to render |
| `--frames N` | frames per clip |
| `--max-actions`, `--max-models` | limits |
| `--variant BIN.CVM/VF1J_COL_03.MRG` | livery |
| `--apply-motions BIN.CVM/AUTH_M01P2N0.CMP` | apply an archive's clips to every rig |
| `--blocks 3` | stage pattern blocks |
| `--engine BLENDER_WORKBENCH` | render engine |

## Verification output (`E:\tests\macross_sdf`)

- `<ASSET>.blend`: importer output, with images packed.
- `<ASSET>__<model>__<view>.png`: rest-pose renders.
- `<ASSET>__<rig>__<clip>_fNNN.png`: animation frames.
- `report.json`: counts, timings, warnings and actions per asset.
- `smoke_all.json`: whole-disc import results.
- `survey.json`: whole-disc format survey.
- `auth_on_vf1j/`: AUTH event clips applied to the VF-1J rigs.

To run the standard set again, see `tools/run_test_set.ps1`.
