"""Skeleton (``.bon``) and motion clip (``.mot``) parsers.

Both start with little-endian u16 magic 0x3B71 and a u16 kind (1 = .bon,
0 = .mot).  See docs/formats/motion.md.

.bon::

    u16 magic, u16 kind=1, u32 bone_count
    bone_count x 72-byte records:
        u32 name offset (file relative, NUL-terminated ASCII)
        u32 flags   (low 16: 0 locator, 1 object, 2 chain root, 3 joint,
                     4 effector; high 16: extra role bits)
        u32 node index in the reference model (do not rely on it - bind by name)
        f32 T[3], R[3] (radians, M = T Rz Ry Rx S), S[3]
        3 x (u32 count, u32 offset) u16 lists: children, constraint A, constraint B

.mot::

    0x00 u16 magic, u16 kind=0
    0x04 f32 (1.0 observed - playback speed?)
    0x08 u32 bone count of the target skeleton
    0x0C u16 flags (bit 1: wide channel entries)
    0x0E u16 frame count
    0x10 u16 frames per second (60)
    0x12 u16 entry count
    0x14 entries: (u8 bone, u8 mask) or, if flags & 2, (u16 bone, u16 mask)
         mask bits 0-2 = rotate XYZ, 3-5 = translate XYZ, 6-8 = scale XYZ
    then one key stream per set mask bit, in entry order and, within an
    entry, grouped translate, rotate, scale (x, y, z each).
    Key header u16: frame = h & 0x1FFF, bit 13 = constant track,
    key type = h >> 14 (am2mFcurveDecode16):
        0x2000: constant for the whole clip (+half value), stream ends
        type 0: key, value 0.0, flat tangents (no payload)
        type 1: key + half value, flat (zero) tangents
        type 2: key + half value + half slope (in = out)
        type 3: key + half value + half in-slope + half out-slope
    Slopes are units per second (divide by the header fps for per-frame);
    evaluation is cubic Hermite between keys (AM2M_FcurveCalc).
    A stream ends after a constant or when a key reaches frame_count - 1.
    Footer: u16 0x2001, u16 0 (+ alignment padding).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = 0x3B71
CHANNELS = ("rx", "ry", "rz", "tx", "ty", "tz", "sx", "sy", "sz")
# Mask bits are R(0-2) T(3-5) S(6-8) but key streams are stored T, R, S.
STREAM_ORDER = (3, 4, 5, 0, 1, 2, 6, 7, 8)


def _half(v: int) -> float:
    return float(np.frombuffer(struct.pack("<H", v), "<f2")[0])


@dataclass
class Bone:
    index: int
    name: str
    flags: int
    node_index: int
    translation: tuple
    rotation: tuple
    scale: tuple
    children: tuple
    list_b: tuple
    list_c: tuple
    parent: int = -1


@dataclass
class Skeleton:
    bones: list[Bone]

    def by_name(self) -> dict[str, Bone]:
        return {b.name: b for b in self.bones}


def parse_bon(data: bytes) -> Skeleton:
    magic, kind, count = struct.unpack_from("<HHI", data, 0)
    if magic != MAGIC or kind != 1:
        raise ValueError("not a .bon skeleton")
    bones = []
    for i in range(count):
        r = 8 + i * 72
        if r + 72 > len(data):
            break
        name_off, flags, node = struct.unpack_from("<III", data, r)
        t = struct.unpack_from("<3f", data, r + 12)
        ro = struct.unpack_from("<3f", data, r + 24)
        s = struct.unpack_from("<3f", data, r + 36)
        lists = []
        for j in range(3):
            n, off = struct.unpack_from("<II", data, r + 48 + 8 * j)
            lists.append(struct.unpack_from(f"<{n}H", data, off) if n and off + 2 * n <= len(data) else ())
        end = data.find(b"\0", name_off)
        name = data[name_off:end].decode("ascii", "replace") if 0 < name_off < len(data) else f"bone_{i}"
        bones.append(Bone(i, name, flags, node, t, ro, s, *lists))
    for b in bones:
        for c in b.children:
            if c < len(bones):
                bones[c].parent = b.index
    return Skeleton(bones)


@dataclass
class Track:
    bone: int
    channel: str              # one of CHANNELS
    constant: float | None    # set when the whole track is constant
    frames: np.ndarray        # key frames (int)
    values: np.ndarray        # key values
    slopes_in: np.ndarray     # per-key incoming slope (units / second)
    slopes_out: np.ndarray

    def sample(self, nframes: int, fps: float = 60.0) -> np.ndarray:
        """Evaluate at integer frames 0..nframes-1 (cubic Hermite; slopes are per second)."""
        if self.constant is not None:
            return np.full(nframes, self.constant, np.float64)
        f = self.frames.astype(np.float64)
        v = self.values
        out = np.empty(nframes, np.float64)
        t = np.arange(nframes, dtype=np.float64)
        if len(f) == 1:
            out[:] = v[0]
            return out
        seg = np.clip(np.searchsorted(f, t, side="right") - 1, 0, len(f) - 2)
        f0, f1 = f[seg], f[seg + 1]
        dt = np.maximum(f1 - f0, 1e-9)
        u = np.clip((t - f0) / dt, 0.0, 1.0)
        p0, p1 = v[seg], v[seg + 1]
        m0 = np.nan_to_num(self.slopes_out[seg]) / fps * dt
        m1 = np.nan_to_num(self.slopes_in[seg + 1]) / fps * dt
        h00 = 2 * u ** 3 - 3 * u ** 2 + 1
        h10 = u ** 3 - 2 * u ** 2 + u
        h01 = -2 * u ** 3 + 3 * u ** 2
        h11 = u ** 3 - u ** 2
        out[:] = h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1
        out[t < f[0]] = v[0]
        out[t > f[-1]] = v[-1]
        return out


@dataclass
class Motion:
    bone_count: int
    flags: int
    frame_count: int
    fps: int
    speed: float
    tracks: list[Track] = field(default_factory=list)
    footer: bytes = b""

    def animated_bones(self) -> set[int]:
        return {t.bone for t in self.tracks}


def parse_mot(data: bytes) -> Motion:
    magic, kind, speed, nbones, flags, nframes, fps, nent = struct.unpack_from("<HHfIHHHH", data, 0)
    if magic != MAGIC or kind != 0:
        raise ValueError("not a .mot clip")
    wide = bool(flags & 2)
    esz = 4 if wide else 2
    entries = [struct.unpack_from("<HH" if wide else "<BB", data, 0x14 + esz * i) for i in range(nent)]
    p = 0x14 + esz * nent
    mot = Motion(nbones, flags, nframes, fps or 60, speed)
    last = max(nframes - 1, 0)
    for bone, mask in entries:
        for bit in STREAM_ORDER:
            if not mask & (1 << bit):
                continue
            frames, vals, sin, sout = [], [], [], []
            const = None
            while True:
                h = struct.unpack_from("<H", data, p)[0]
                p += 2
                typ, fr = h >> 13, h & 0x1FFF
                if typ == 1:
                    const = _half(struct.unpack_from("<H", data, p)[0])
                    p += 2
                    break
                if typ == 0:
                    v, a, b = 0.0, 0.0, 0.0
                elif typ == 2:
                    v = _half(struct.unpack_from("<H", data, p)[0]); p += 2
                    a = b = 0.0
                elif typ == 4:
                    hv, hs = struct.unpack_from("<HH", data, p); p += 4
                    v = _half(hv); a = b = _half(hs)
                elif typ == 6:
                    hv, ha, hb = struct.unpack_from("<HHH", data, p); p += 6
                    v = _half(hv); a = _half(ha); b = _half(hb)
                else:
                    raise ValueError(f"unknown key type {typ} at 0x{p - 2:X}")
                frames.append(fr); vals.append(v); sin.append(a); sout.append(b)
                if fr >= last:
                    break
            mot.tracks.append(Track(bone, CHANNELS[bit], const, np.array(frames, np.int32),
                                    np.array(vals, np.float64), np.array(sin, np.float64),
                                    np.array(sout, np.float64)))
    mot.footer = data[p:]
    return mot


def sample_pose(mot: Motion, skel_rest: list[tuple], frame_count: int | None = None) -> np.ndarray:
    """Return (frames, bones, 9) local channel values (rx ry rz tx ty tz sx sy sz).

    ``skel_rest`` gives the rest (R, T, S) tuples used for unanimated channels.
    """
    n = frame_count or max(mot.frame_count, 1)
    nb = len(skel_rest)
    out = np.zeros((n, nb, 9), np.float64)
    for i, (r, t, s) in enumerate(skel_rest):
        out[:, i, 0:3] = r
        out[:, i, 3:6] = t
        out[:, i, 6:9] = s
    for tr in mot.tracks:
        if tr.bone < nb:
            out[:, tr.bone, CHANNELS.index(tr.channel)] = tr.sample(n, mot.fps or 60)
    return out
