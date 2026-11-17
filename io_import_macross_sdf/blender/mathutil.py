"""Vectorised matrix helpers (numpy) shared by the Blender builders.

Game space: right-handed, +Y up, models face -Z, local transform
``M = T * Rz * Ry * Rx * S`` (column vectors; see gfxSetObjSub).
Blender space: right-handed, +Z up, models face -Y.
Conversion: ``(x, y, z)_blender = (-x, z, y)_game`` (a proper rotation,
det = +1), applied to matrices as ``C @ M @ C^-1``.
"""

from __future__ import annotations

import numpy as np

C3 = np.array([[-1.0, 0.0, 0.0],
               [0.0, 0.0, 1.0],
               [0.0, 1.0, 0.0]])
C4 = np.eye(4)
C4[:3, :3] = C3
C4_INV = np.linalg.inv(C4)


def euler_xyz(r: np.ndarray) -> np.ndarray:
    """r (...,3) radians -> (...,3,3) = Rz @ Ry @ Rx."""
    r = np.asarray(r, np.float64)
    cx, cy, cz = np.cos(r[..., 0]), np.cos(r[..., 1]), np.cos(r[..., 2])
    sx, sy, sz = np.sin(r[..., 0]), np.sin(r[..., 1]), np.sin(r[..., 2])
    m = np.empty(r.shape[:-1] + (3, 3))
    m[..., 0, 0] = cz * cy
    m[..., 0, 1] = cz * sy * sx - sz * cx
    m[..., 0, 2] = cz * sy * cx + sz * sx
    m[..., 1, 0] = sz * cy
    m[..., 1, 1] = sz * sy * sx + cz * cx
    m[..., 1, 2] = sz * sy * cx - cz * sx
    m[..., 2, 0] = -sy
    m[..., 2, 1] = cy * sx
    m[..., 2, 2] = cy * cx
    return m


def trs(t: np.ndarray, r: np.ndarray, s: np.ndarray) -> np.ndarray:
    """(...,3) x3 -> (...,4,4) = T @ Rz Ry Rx @ S."""
    t = np.asarray(t, np.float64)
    m = np.zeros(t.shape[:-1] + (4, 4))
    m[..., :3, :3] = euler_xyz(r) * np.asarray(s, np.float64)[..., None, :]
    m[..., :3, 3] = t
    m[..., 3, 3] = 1.0
    return m


def to_blender(m: np.ndarray) -> np.ndarray:
    return C4 @ m @ C4_INV


def topo_order(parents: list[int]) -> list[int]:
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


def world_from_local(local: np.ndarray, parents: list[int], order=None) -> np.ndarray:
    """local (...,n,4,4) -> world (...,n,4,4)."""
    order = order or topo_order(parents)
    world = np.empty_like(local)
    for i in order:
        p = parents[i]
        world[..., i, :, :] = local[..., i, :, :] if p < 0 else world[..., p, :, :] @ local[..., i, :, :]
    return world


def orthonormalize(m3: np.ndarray) -> np.ndarray:
    """Closest rotation (polar decomposition) for (...,3,3)."""
    u, _, vt = np.linalg.svd(m3)
    r = u @ vt
    d = np.linalg.det(r)
    u[..., :, 2] *= np.where(d < 0, -1.0, 1.0)[..., None]
    return u @ vt


def decompose(m: np.ndarray):
    """(...,4,4) -> loc (...,3), quat wxyz (...,4), scale (...,3)."""
    loc = m[..., :3, 3]
    a = m[..., :3, :3]
    sc = np.linalg.norm(a, axis=-2)
    sc = np.where(sc < 1e-12, 1e-12, sc)
    r = a / sc[..., None, :]
    neg = np.linalg.det(r) < 0
    sc = np.where(neg[..., None], sc * np.array([-1.0, 1.0, 1.0]), sc)
    r = np.where(neg[..., None, None], r * np.array([-1.0, 1.0, 1.0])[None, :], r)
    r = orthonormalize(r)
    return loc, mat_to_quat(r), sc


def mat_to_quat(r: np.ndarray) -> np.ndarray:
    """(...,3,3) rotation -> (...,4) quaternion w,x,y,z (Shepperd)."""
    r = np.asarray(r)
    shp = r.shape[:-2]
    r = r.reshape(-1, 3, 3)
    q = np.empty((len(r), 4))
    tr = r[:, 0, 0] + r[:, 1, 1] + r[:, 2, 2]
    c0 = tr > 0
    c1 = (~c0) & (r[:, 0, 0] >= r[:, 1, 1]) & (r[:, 0, 0] >= r[:, 2, 2])
    c2 = (~c0) & (~c1) & (r[:, 1, 1] >= r[:, 2, 2])
    c3 = ~(c0 | c1 | c2)
    s = np.sqrt(np.maximum(tr[c0] + 1.0, 1e-30)) * 2
    q[c0] = np.stack([0.25 * s, (r[c0, 2, 1] - r[c0, 1, 2]) / s, (r[c0, 0, 2] - r[c0, 2, 0]) / s,
                      (r[c0, 1, 0] - r[c0, 0, 1]) / s], 1)
    s = np.sqrt(np.maximum(1.0 + r[c1, 0, 0] - r[c1, 1, 1] - r[c1, 2, 2], 1e-30)) * 2
    q[c1] = np.stack([(r[c1, 2, 1] - r[c1, 1, 2]) / s, 0.25 * s, (r[c1, 0, 1] + r[c1, 1, 0]) / s,
                      (r[c1, 0, 2] + r[c1, 2, 0]) / s], 1)
    s = np.sqrt(np.maximum(1.0 + r[c2, 1, 1] - r[c2, 0, 0] - r[c2, 2, 2], 1e-30)) * 2
    q[c2] = np.stack([(r[c2, 0, 2] - r[c2, 2, 0]) / s, (r[c2, 0, 1] + r[c2, 1, 0]) / s, 0.25 * s,
                      (r[c2, 1, 2] + r[c2, 2, 1]) / s], 1)
    s = np.sqrt(np.maximum(1.0 + r[c3, 2, 2] - r[c3, 0, 0] - r[c3, 1, 1], 1e-30)) * 2
    q[c3] = np.stack([(r[c3, 1, 0] - r[c3, 0, 1]) / s, (r[c3, 0, 2] + r[c3, 2, 0]) / s,
                      (r[c3, 1, 2] + r[c3, 2, 1]) / s, 0.25 * s], 1)
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    return q.reshape(shp + (4,))


def make_quat_continuous(q: np.ndarray) -> np.ndarray:
    """q (frames, ..., 4): flip signs so consecutive frames have positive dot."""
    q = q.copy()
    for f in range(1, len(q)):
        d = np.sum(q[f] * q[f - 1], axis=-1)
        q[f][d < 0] *= -1
    return q
