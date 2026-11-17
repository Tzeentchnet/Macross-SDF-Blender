"""High-level asset discovery: turn any disc file into models/textures/motions.

This is the neutral layer the Blender adapter consumes.  Nothing here imports
``bpy``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import gfx2obj, mrg, motion, stage, tim2

LOD_RE = re.compile(r"(?:_lod_([lms])_|_([lmsLMS])_\d+(?:_|\.mdl$|$))")


def lod_of(name: str) -> str:
    """Return 'l', 'm', 's' or '' for a model leaf name."""
    m = LOD_RE.search(name)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or "").lower()


def stem(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    return os.path.splitext(base)[0].strip().lower()


@dataclass
class ModelEntry:
    name: str
    path: str
    data: bytes
    lod: str = ""
    _parsed: gfx2obj.Model | None = None

    @property
    def model(self) -> gfx2obj.Model:
        if self._parsed is None:
            self._parsed = gfx2obj.parse(self.data)
        return self._parsed


@dataclass
class MotionEntry:
    name: str
    path: str
    data: bytes
    _parsed: motion.Motion | None = None

    @property
    def motion(self) -> motion.Motion:
        if self._parsed is None:
            self._parsed = motion.parse_mot(self.data)
        return self._parsed


@dataclass
class SkeletonEntry:
    name: str
    path: str
    skeleton: motion.Skeleton


@dataclass
class Bundle:
    name: str
    tree: mrg.Node
    models: list[ModelEntry] = field(default_factory=list)
    textures: dict[str, bytes] = field(default_factory=dict)       # stem -> TIM2 bytes
    texture_paths: dict[str, str] = field(default_factory=dict)
    motions: list[MotionEntry] = field(default_factory=list)
    skeletons: list[SkeletonEntry] = field(default_factory=list)
    collisions: list[tuple[str, bytes]] = field(default_factory=list)
    stage: stage.StageLayout | None = None
    stage_models: dict[str, ModelEntry] = field(default_factory=dict)  # stem -> model

    _pictures: dict = field(default_factory=dict)

    def picture(self, tex_name: str):
        """Decode (and cache) the first picture of the texture called tex_name."""
        key = stem(tex_name)
        if key in self._pictures:
            return self._pictures[key]
        data = self.textures.get(key)
        pic = None
        if data is not None:
            try:
                pics = tim2.parse(data)
                pic = pics[0] if pics else None
            except Exception:
                pic = None
        self._pictures[key] = pic
        return pic


def load_bundle(data: bytes, name: str) -> Bundle:
    tree = mrg.build_tree(data, name)
    b = Bundle(name, tree)
    for n in tree.walk():
        if n.kind == "gfx2obj":
            b.models.append(ModelEntry(n.name, n.path, n.data, lod_of(n.name)))
        elif n.kind == "tim2":
            k = stem(n.name)
            if k not in b.textures:
                b.textures[k] = n.data
                b.texture_paths[k] = n.path
        elif n.kind == "mot":
            b.motions.append(MotionEntry(stem(n.name), n.path, n.data))
        elif n.kind == "bon":
            try:
                b.skeletons.append(SkeletonEntry(stem(n.name), n.path, motion.parse_bon(n.data)))
            except Exception:
                pass
        elif n.kind == "collision":
            b.collisions.append((n.path, n.data))
    _detect_stage(b)
    return b


def _child(node: mrg.Node, needle: str):
    for c in node.children:
        if needle.lower() in c.name.lower():
            return c
    return None


def _detect_stage(b: Bundle):
    t = b.tree
    pat = _child(t, "GRD_PatTbl")
    param = _child(t, "GRD_Param")
    if pat is None and param is None:
        return
    lay = stage.StageLayout()
    arr = _child(t, "GRD_ObjArr")
    if arr is not None:
        lay.arrangements = [stage.parse_arrangement(c.data) for c in arr.children]
    if pat is not None and pat.children:
        lay.pattern_count, lay.side, lay.tile_grids, lay.arr_grids = stage.parse_pattern(
            [c.data for c in pat.children], arr is not None)
    if param is not None:
        lay.param_raw = param.data
    b.stage = lay
    for m in b.models:
        b.stage_models[stem(m.name)] = m


# ---------------------------------------------------------------------------
# Skeleton matching

def node_names(model: gfx2obj.Model) -> set[str]:
    return {n.name.lower() for n in model.nodes}


def skeleton_score(skel: motion.Skeleton, model: gfx2obj.Model) -> float:
    names = node_names(model)
    if not skel.bones:
        return 0.0
    hit = sum(1 for bn in skel.bones if bn.name.lower() in names)
    return hit / len(skel.bones)


def best_skeleton(skeletons: list[SkeletonEntry], model: gfx2obj.Model, bone_count: int | None = None):
    best, score = None, 0.0
    for s in skeletons:
        if bone_count is not None and len(s.skeleton.bones) != bone_count:
            continue
        sc = skeleton_score(s.skeleton, model)
        if sc > score:
            best, score = s, sc
    return best, score


# Which disc archives hold the shared skeleton/motion sets for a bundle.
MOTION_ARCHIVE_HINTS = [
    (re.compile(r"^VF1D|^VF1DSP|^VF1D_SP"), ["MOT_GER_VF1D.MRG", "MOT_BAT_VF1.MRG"]),
    (re.compile(r"^VF1J?AMD"), ["MOT_GER_VF1.MRG", "MOT_BAT_VF1.MRG"]),
    (re.compile(r"^(VF1|VT1)"), ["MOT_GER_VF1.MRG", "MOT_BAT_VF1.MRG"]),
    (re.compile(r"^VE1"), ["MOT_GER_VE1.MRG"]),
    (re.compile(r"^VF4"), ["MOT_GER_VF4.MRG", "MOT_BAT_VF4.MRG"]),
    (re.compile(r"^ENM_GLG"), ["MOT_GLAUG.MRG"]),
    (re.compile(r"^ENM_RGN|^ENM_RGT"), ["MOT_REGULT.MRG"]),
    (re.compile(r"^ENM_NJD"), ["MOT_NOUSJA.MRG"]),
    (re.compile(r"^ENM_QDL"), ["MOT_QUEAD.MRG"]),
    (re.compile(r"^ENM_POD"), ["MOT_POD.MRG"]),
    (re.compile(r"^ENM_DFN"), ["MOT_DEFENDER.MRG"]),
    (re.compile(r"^ENM_TMF|^ENM_TMH"), ["MOT_TOMAHAWK.MRG"]),
    (re.compile(r"^ENM_PLN|^ENM_PHX"), ["MOT_PHALANX.MRG"]),
    (re.compile(r"^ENM_MNSA"), ["MOT_MONSTERA.MRG"]),
    (re.compile(r"^ENM_MNS"), ["MOT_MONSTER.MRG"]),
    (re.compile(r"^ENM_KAISA"), ["MOT_KAISHUA.MRG"]),
    (re.compile(r"^ENM_KAIS"), ["MOT_KAISHU.MRG"]),
    (re.compile(r"^ENM_CATS"), ["MOT_CATS.MRG"]),
    (re.compile(r"^ENM_BK"), ["MOT_BREAK.MRG"]),
    (re.compile(r"^ENM_SDF_DP"), ["MOT_SDF_DPT.MRG"]),
    (re.compile(r"^ENM_SDF_BK"), ["MOT_SDF_BK.MRG"]),
    (re.compile(r"^ENM_SDF_AM"), ["MOT_SDF_AM.MRG"]),
    (re.compile(r"^ENM_SDF"), ["MOT_SDF.MRG"]),
]


def motion_archives_for(file_name: str) -> list[str]:
    base = file_name.replace("\\", "/").split("/")[-1].upper()
    for rx, names in MOTION_ARCHIVE_HINTS:
        if rx.search(base):
            return names
    return []


def color_variants_for(file_name: str, disc_files: list[str]) -> list[str]:
    """VF1J_AC.CMP -> [BIN.CVM/VF1J_COL_00.MRG, ...] (alternate liveries)."""
    base = file_name.replace("\\", "/").split("/")[-1].upper()
    m = re.match(r"^(VF1[A-Z]*?)(?:H|M|X|K|F)?_AC\.CMP$", base)
    if not m:
        return []
    prefix = m.group(1)
    out = [f for f in disc_files if f.upper().split("/")[-1].startswith(prefix + "_COL_")]
    return sorted(out)
