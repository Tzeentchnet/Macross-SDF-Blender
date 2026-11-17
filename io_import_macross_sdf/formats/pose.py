"""Evaluate a .mot clip on a .bon skeleton exactly like the game (FK + IK).

Re-implemented from the game's ``_am2mMotionCalc`` / ``am2mMotionCalcChain``
/ ``am2mMotionCalcMatrix`` (see docs/formats/motion.md):

* Track values of rx, ry and tz are stored negated (Softimage authoring
  space); rz, tx, ty and scale are used as stored.  Channels without a track
  use the skeleton rest values (already in game space).
* Local matrix = T * Rz * Ry * Rx * S.
* Node type (bone flags & 0xFFFF): 0 locator, 1 object, 2 chain root,
  3 joint, 4 effector.  Chain roots carry the joint count in flags >> 16.
* A chain is solved by IK only when its effector has a translation track;
  the effector translation is then the target position in skeleton-root
  space.  Otherwise the joints use FK.  (The game unfolds every track -
  including constant ones - into a curve, so the per-channel constant
  fields keep the skeleton rest values.)
* Effectors are always placed at T(rest bone length) * R(own rotation
  channels) relative to the last joint.
"""

from __future__ import annotations

import numpy as np

from . import motion as motmod

NEGATED = (0, 1, 5)  # rx, ry, tz
TWIST_JOINTS = ("j_kata_l", "j_kata_r")


def _rx(a):
    c, s = np.cos(a), np.sin(a)
    m = np.zeros(np.shape(a) + (4, 4))
    m[..., 0, 0] = 1
    m[..., 1, 1] = c
    m[..., 1, 2] = -s
    m[..., 2, 1] = s
    m[..., 2, 2] = c
    m[..., 3, 3] = 1
    return m


def _ry_sc(s, c):
    m = np.zeros(np.shape(s) + (4, 4))
    m[..., 0, 0] = c
    m[..., 0, 2] = s
    m[..., 1, 1] = 1
    m[..., 2, 0] = -s
    m[..., 2, 2] = c
    m[..., 3, 3] = 1
    return m


def _rz_sc(s, c):
    m = np.zeros(np.shape(s) + (4, 4))
    m[..., 0, 0] = c
    m[..., 0, 1] = -s
    m[..., 1, 0] = s
    m[..., 1, 1] = c
    m[..., 2, 2] = 1
    m[..., 3, 3] = 1
    return m


def _trans(t):
    t = np.asarray(t, np.float64)
    m = np.zeros(t.shape[:-1] + (4, 4))
    m[..., 0, 0] = m[..., 1, 1] = m[..., 2, 2] = m[..., 3, 3] = 1
    m[..., :3, 3] = t
    return m


def _euler(r):
    r = np.asarray(r, np.float64)
    cx, cy, cz = np.cos(r[..., 0]), np.cos(r[..., 1]), np.cos(r[..., 2])
    sx, sy, sz = np.sin(r[..., 0]), np.sin(r[..., 1]), np.sin(r[..., 2])
    m = np.zeros(r.shape[:-1] + (4, 4))
    m[..., 0, 0] = cz * cy
    m[..., 0, 1] = cz * sy * sx - sz * cx
    m[..., 0, 2] = cz * sy * cx + sz * sx
    m[..., 1, 0] = sz * cy
    m[..., 1, 1] = sz * sy * sx + cz * cx
    m[..., 1, 2] = sz * sy * cx - cz * sx
    m[..., 2, 0] = -sy
    m[..., 2, 1] = cy * sx
    m[..., 2, 2] = cy * cx
    m[..., 3, 3] = 1
    return m


def trs(ch: np.ndarray) -> np.ndarray:
    """ch (...,9) = rx ry rz tx ty tz sx sy sz -> (...,4,4)."""
    m = _euler(ch[..., 0:3])
    m[..., :3, :3] *= ch[..., None, 6:9]
    m[..., :3, 3] = ch[..., 3:6]
    return m


def channels(skel: motmod.Skeleton, mot: motmod.Motion, frames: int | None = None):
    """Per-frame game-space channels (F, nb, 9) and a (nb, 9) 'keyed' mask."""
    n = frames or max(mot.frame_count, 1)
    nb = len(skel.bones)
    ch = np.zeros((n, nb, 9))
    keyed = np.zeros((nb, 9), bool)
    for i, b in enumerate(skel.bones):
        ch[:, i, 0:3] = b.rotation
        ch[:, i, 3:6] = b.translation
        ch[:, i, 6:9] = b.scale
    for tr in mot.tracks:
        if tr.bone >= nb:
            continue
        ci = motmod.CHANNELS.index(tr.channel)
        v = tr.sample(n, mot.fps or 60)
        if ci in NEGATED:
            v = -v
        ch[:, tr.bone, ci] = v
        keyed[tr.bone, ci] = True  # any track (constant tracks are unfolded as 1-key curves)
    return ch, keyed


def evaluate(skel: motmod.Skeleton, mot: motmod.Motion, frames: int | None = None,
             ik: bool = True) -> np.ndarray:
    """Return per-frame local matrices (F, nb, 4, 4) for every skeleton bone."""
    bones = skel.bones
    nb = len(bones)
    ch, keyed = channels(skel, mot, frames)
    F = ch.shape[0]
    local = trs(ch)
    world = np.zeros_like(local)
    types = [b.flags & 0xFFFF for b in bones]
    rest_t = np.array([b.translation for b in bones], np.float64)

    # effectors: translation = constant bone length (rest or constant track)
    eff_target = {}
    for i, b in enumerate(bones):
        if types[i] == 4:
            eff_target[i] = ch[:, i, 3:6].copy()
            local[:, i, :3, 3] = rest_t[i]

    order = _topo([b.parent for b in bones])
    solved: set[int] = set()
    for i in order:
        p = bones[i].parent
        if i not in solved:
            world[:, i] = local[:, i] if p < 0 else world[:, p] @ local[:, i]
        else:
            world[:, i] = world[:, p] @ local[:, i]
        if not ik or types[i] != 2:
            continue
        nj = bones[i].flags >> 16
        chain = _chain(bones, i, nj)
        if chain is None:
            continue
        j1, j2, eff = chain
        if not keyed[eff, 3:6].any():
            continue  # FK: joints keep their own channels
        m_cur = world[:, i] @ _trans(local[:, j1, :3, 3])
        tgt = np.concatenate([eff_target[eff], np.ones((F, 1))], 1)
        pv = np.einsum("fij,fj->fi", np.linalg.inv(m_cur), tgt)[:, :3]
        x, y, z = pv[:, 0], pv[:, 1], pv[:, 2]
        lxy = np.sqrt(x * x + y * y)
        d = np.sqrt(lxy * lxy + z * z)
        safe_xy = np.where(lxy > 1e-9, lxy, 1.0)
        safe_d = np.where(d > 1e-9, d, 1.0)
        aim = _rz_sc(np.where(lxy > 1e-9, y / safe_xy, 0.0), np.where(lxy > 1e-9, x / safe_xy, 1.0)) @ \
            _ry_sc(np.where(d > 1e-9, -z / safe_d, 0.0), np.where(d > 1e-9, lxy / safe_d, 1.0))
        if nj == 1 or j2 is None:
            rot1 = aim
            twist = np.zeros(F)
        else:
            L1 = float(abs(local[0, j2, 0, 3])) or float(np.linalg.norm(rest_t[j2]))
            L2 = float(abs(local[0, eff, 0, 3])) or float(np.linalg.norm(rest_t[eff]))
            flag = bones[j2].flags >> 16
            c1 = np.clip((L1 * L1 + d * d - L2 * L2) / np.maximum(2 * L1 * d, 1e-9), -1, 1)
            s1 = np.sqrt(1 - c1 * c1) * (1.0 if flag else -1.0)
            rot1 = aim @ _rz_sc(s1, c1)
            twist = np.zeros(F)
            if bones[j1].name in TWIST_JOINTS:
                twist = np.arctan2(rot1[:, 2, 1], rot1[:, 2, 2])
                rot1 = rot1 @ _rx(-twist)
            c2 = np.clip((L1 * L1 + L2 * L2 - d * d) / max(2 * L1 * L2, 1e-9), -1, 1)
            s2 = np.sqrt(1 - c2 * c2) * (-1.0 if flag else 1.0)
            rot2 = _rz_sc(s2, -c2) @ _ry_sc(np.sin(-twist), np.cos(-twist)) @ _rx(np.full(F, bones[j2].rotation[0]))
            m2 = rot2.copy()
            m2[:, :3, 3] = local[:, j2, :3, 3]
            local[:, j2] = m2
            solved.add(j2)
        m1 = rot1.copy()
        m1[:, :3, 3] = local[:, j1, :3, 3]
        local[:, j1] = m1
        solved.add(j1)
    return local


def _chain(bones, root: int, nj: int):
    def first_child(i, want=None):
        for c in bones[i].children:
            if c < len(bones) and (want is None or (bones[c].flags & 0xFFFF) == want):
                return c
        return None

    j1 = first_child(root, 3)
    if j1 is None:
        return None
    if nj >= 2:
        j2 = first_child(j1, 3)
        if j2 is None:
            return None
        eff = first_child(j2, 4)
    else:
        j2 = None
        eff = first_child(j1, 4)
    if eff is None:
        return None
    return j1, j2, eff


def _topo(parents):
    n = len(parents)
    order, seen = [], [False] * n

    def visit(i, depth=0):
        if seen[i] or depth > n:
            return
        p = parents[i]
        if 0 <= p < n and not seen[p]:
            visit(p, depth + 1)
        seen[i] = True
        order.append(i)

    for i in range(n):
        visit(i)
    return order
