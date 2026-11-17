# Asset catalogue (SLPM-65405)

Counts come from a full parse of the disc
(`tools/blender_smoke_all.py` and [`tools/survey_disc.py`](../tools/survey_disc.py)).

Leaf counts across all containers:

| leaf type | count |
|---|---:|
| GFX2OBJ models | 7,989 (7,668 `0100`, 321 `0200`; 2,253,288 vertices, 1,264,080 triangles) |
| MRG archives | 3,221 |
| TIM2 textures | 2,997 (2,975 swizzled, 22 linear) |
| list manifests | 2,181 |
| collision (CLS) | 725 |
| AUTH event blocks | 604 |
| motion clips (`.mot`) | 469 (63,460 tracks) |
| MRGA (menu) | 175 |
| skeletons (`.bon`) | 28 |
| unidentified raw | 1,379 |

## BIN.CVM

| family | files | content | importer |
|---|---:|---|---|
| `VF1*_AC.CMP`, `VT1*`, `VE1_AC`, `VF4_AC` | 37 | player craft: fighter (`_f`) + Battroid (`_b`) models in 3 LODs, hard points, transformation clips, textures. Suffixes H/M/X/K/F/SP/ST/AMD are loadout/pilot variants. | full (rig + clips + shared MOT sets) |
| `VF1*_COL_00…05.MRG` | 54 | alternative liveries (textures only) | colour-variant option |
| `MOT_*.MRG` | 24 | skeleton + clip sets (`MOT_GER_*` Gerwalk/fighter FK, `MOT_BAT_*` Battroid IK, enemy sets) | clips → actions; also *Motions onto Rig* |
| `ENM_*.CMP` | 51 | enemies and allies: Zentradi mecha (GLG Glaug, RGN/RGT Regult variants, NJD Nousjadeul-Ger, QDL Queadluun-Rau, POD), SDF ships/units, missiles, cars; `_F` = fallen/damaged variants | full |
| `GD_xx.CMP` | 40 | stages ([formats/stage.md](formats/stage.md)) | layout + instancing |
| `AUTH_*.CMP` | 62 | in-engine event scenes: AUTH script, set models/textures, clips for the player craft, lights, SE | models; clips via *Motions onto Rig*; script not decoded |
| `FX.CMP`, `FX_00…49.CMP` | 51 | effect meshes and textures (explosions, beams, vapour) | models (unlit/translucent) |
| `EMBLEM.MRG`, `EMB_*.MRG` | 8 | emblem/decal models and textures | models |
| `SHD_*.MRG` | 4 | shadow meshes | models |
| `CB_*.MRG` | 11 | unknown (per-enemy "CB" data – collision/behaviour?) | parsed generically |
| `MCRS*.MSD` | 32 | mission data (sound banks `IECS…`, `SECTver0.502` sections) | not decoded |
| `MIS_*PH*.MRG` | 47 | mission phase tables (`_enm.bin`, `_gen.bin`, `_abs.pos`, `_rel.bin`, `_stg.bin`) | not decoded |
| `CAMPATH*.CMP`, `CAM_BURITAI.CMP` | 7 | camera paths | not decoded |
| `GLB_DATA_*`, `BRF_DATA_*`, `LOAD_*`, `MENU_*`, `COVER`, `SCRAMBLE_DATA` | 59 | briefing/loading/menu data | models/textures where present |
| `CHRW*.CHRW/.CAT` | 3 | character catalogue (portrait data) | textures |
| `EVT_*.AUT`, `SCENE1.AUT` | 3 | standalone AUTH scripts | not decoded |

## JPN.CVM

Menus (`MENU*.CMP`, `TTL`, `LOGO`, `RSLT`), briefing scenes
(`BRF_AUTH_*`, `GLB_AUTH_*`, `MENU_AUTH*`; `menu_mdl.mrg` holds indexed
`0100` models), subtitles (`SBTTL_*`), fonts (`CRSDAT*.MRG`) and
`BOOTDAT.CMP` (script text). The models and textures import through the
generic path.

## Other containers

- `ADXJ.CVM`: ADX music and dialogue plus `MCRSVOICE.AFS` (2,926 voices). Use vgmstream.
- `MOV.CVM`: Sofdec `.SFD` movies.

These are outside the importer's scope.
