# Skeletons (`.bon`), motion clips (`.mot`) and the motion evaluator

Code: [`formats/motion.py`](../../io_import_macross_sdf/formats/motion.py)
(parsing) and [`formats/pose.py`](../../io_import_macross_sdf/formats/pose.py)
(game-accurate FK + IK).

Confidence: **confirmed** for parsing (all 469 clips and 28 skeletons) and
for FK/IK maths. The IK maths was re-implemented from the game's
`am2mMotionCalcChain` and checked visually on VF-1 fighter, Gerwalk,
Battroid and transformation clips. With these rules, solved IK effectors land
on their targets: residual ≈ 0 for legs, < 0.2 units for arms.

## Engine functions

| symbol | role |
|---|---|
| `MOT_UnfoldBoneData`, `mot_Unfold*` | expand `.bon`/`.mot` into per-node channel curves |
| `_am2mMotionCalc` (0x27F220) | recursive evaluator; dispatches on node type |
| `am2mMotionCalcMatrix` (0x27E8A0) | FK channel evaluation; negates rx, ry, tz curve values |
| `am2mMotionCalcChain` (0x27DC60) | 1- and 2-joint IK solver |
| `AM2M_FcurveCalc` (0x27D260) | cubic Hermite evaluation |
| `am2mFcurveDecode16` (0x27D510) | 16-bit key decoder |

## `.bon` skeleton

```
u16 0x3B71, u16 kind = 1, u32 bone_count
bone_count × 72 bytes:
  u32 name offset (file-relative ASCII)
  u32 flags   low 16 = node type, high 16 = type-specific count/flag
  u32 node index in the authoring model (unreliable across variants - bind by NAME)
  f32 T[3], R[3], S[3]            rest values, game space
  (u32 count, u32 offset) × 3     u16 lists: children, constraint A, constraint B
```

Node types (they match `_am2mMotionCalc`'s jump table):

| type | prefix | evaluation |
|---|---|---|
| 0 | `kl_`, `tg_`, `kg_`, `dy_` | locator: FK (matrix not stored) |
| 1 | `obj_`, `tform_` | object: FK, matrix stored |
| 2 | `cl_`, `c_` | **chain root**: FK, then solve the chain. `flags >> 16` = joint count (1 or 2). |
| 3 | `j_` | joint: matrix produced by the chain solve (or FK when IK is inactive) |
| 4 | `l_` | **effector**: `T(rest bone length) · R(own rotation channels)` relative to the last joint |

On a joint, `flags >> 16` is the bend side for the second joint of a
2-joint chain: 1 on knees, 0 on elbows.

Constraint lists appear on `dy_*` (dynamic cover) bones and on `tform_*`:
`(6,0,j)`, `(9,0,c)`, `(3,)`, `(1,)`. They are evaluated by a callback table
at 0x385B20 / 0x385AC0. **Not implemented yet**; see
[../issues.md](../issues.md).

## `.mot` clip

```
0x00 u16 0x3B71, u16 kind = 0
0x04 f32 speed (1.0)
0x08 u32 bone count of the target skeleton
0x0C u16 flags   bit 1: wide entries
0x0E u16 frame count
0x10 u16 fps (60)
0x12 u16 entry count
0x14 entries: (u8 bone, u8 mask)  or (u16 bone, u16 mask) when wide
      mask bits: 0-2 rotate XYZ, 3-5 translate XYZ, 6-8 scale XYZ
      (narrow clips sometimes end with a dummy entry with mask 0)
then key streams, entry by entry. Within an entry the order is
      translate xyz, rotate xyz, scale xyz   <-- not bit order
footer: u16 0x2001, u16 0, alignment padding
```

### Key streams

Each stream is a sequence of u16 headers, each followed by a 0–3-half payload:

| header | payload | meaning |
|---|---|---|
| `0x2000` (bit 13) | value | constant for the whole clip; the stream ends |
| type 0 (`h >> 14`) | – | key at `h & 0x1FFF` with value 0, flat tangents |
| type 1 | value | key, flat (zero) tangents |
| type 2 | value, slope | key, in = out slope |
| type 3 | value, in, out | key with split tangents |

A stream ends when a key reaches `frame_count - 1`.

The 16-bit numbers are IEEE half floats. The game converts them with
`(h & 0x7FFF) << 13 + 0x38000000`, without denormal handling.

Slopes are **units per second**: divide by the header fps. Evaluation is the
standard cubic Hermite between neighbouring keys (`AM2M_FcurveCalc`). Treating
type-1 keys as linear, or slopes as per-frame, produces wild overshoots.

### Sign convention

The game negates the **rx, ry and tz** values of every track
(`am2mMotionCalcMatrix` multiplies the curve result by −1.0). This is a
Z-mirror out of the Softimage authoring space. rz, tx, ty and scale are used
as stored. Statistics over all clips confirm it: constant and first-key
values equal the `.bon` rest values after negating rx, ry and tz.

## IK (`am2mMotionCalcChain`)

IK is active when the chain's effector has any translation track. Every track
is unfolded as a curve, so the constant fields keep the `.bon` rest values.
When IK is inactive, the joints use their own rotation channels (FK).

```
M     = world(chain root) · T(j1.translation)
p     = M⁻¹ · target            (target = effector translation, skeleton-root space)
aim   = RotZ(atan2(py, px)) · RotY(sin = -pz/|p|, cos = |pxy|/|p|)

1 joint : j1.rot = aim

2 joints: L1 = |j2.translation|, L2 = |effector rest translation|, d = |p|
          c1 = (L1² + d² - L2²) / (2 L1 d),   s1 = ±sqrt(1-c1²)  (- if j2 flag == 0)
          j1.rot = aim · RotZ(s1, c1)
          if j1.name in (j_kata_l, j_kata_r):   # shoulder twist removal
              tw = euler_x(j1.rot);  j1.rot = j1.rot · RotX(-tw)
          c2 = (L1² + L2² - d²) / (2 L1 L2),  s2 = ±sqrt(1-c2²)  (+ if j2 flag == 0)
          j2.rot = RotZ(s2, -c2) · RotY(-tw) · RotX(j2.rest_rx)
```

The chain-root rotation (animated) therefore controls the bend plane: it
acts as the pole vector. The effector is placed at the end of j2, and its
children (hands, feet) follow. The target only steers the joints.

Effector-offset tables (0x64DF80…) are selected by runtime flags
0x08000000–0x80000000. They appear to be used for gameplay aiming and are
treated as zero.

## Binding clips to models

- Clips index skeleton bones. Bones bind to model nodes **by name**, case-insensitive.
- Skeletons live in `MOT_*.MRG`, or inside `VF1JAMD*_AC.CMP` for the armoured VF-1. Craft bundles carry only their transformation clips.
- The importer chooses the skeleton with the same bone count and the highest name overlap. A hint table maps file prefixes to archives, with the whole disc as fallback.
- Clips without a matching skeleton, whose bone count equals the model's node count, bind by node index. This applies to nameless `0100` models.

| skeleton | bones | used by |
|---|---|---|
| `MOT_GER_VF1/S00_Fighter.bon` | 56 | VF-1 fighter/Gerwalk model (`b00_lod_l_f`), transformation clips `T00/T01` |
| `MOT_BAT_VF1/S01_Battroidl.bon` | 49 | VF-1 Battroid model (`b01_lod_l_b`) |
| `MOT_GER_VE1` / `MOT_GER_VF4` | 60 / 58 | VE-1, VF-4 |
| `MOT_GLAUG`, `MOT_REGULT`, `MOT_NOUSJA`, `MOT_QUEAD` … | 11–34 | Zentradi mecha (all IK legs) |
| `AUTH_*.CMP/*.mtn` | 49 / 56 | event-specific clips for the player craft |
