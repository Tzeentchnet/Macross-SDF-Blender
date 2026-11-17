"""Top-level import orchestration (bundle -> scene)."""

from __future__ import annotations

import os
import re

import bpy
import numpy as np

from ..formats import assets, iso, mrg, motion
from . import build
from . import mathutil as mu


def _new_collection(name: str, parent=None):
    col = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(col)
    return col


def _layer_collection(col, root=None):
    root = root or bpy.context.view_layer.layer_collection
    if root.collection == col:
        return root
    for c in root.children:
        r = _layer_collection(col, c)
        if r:
            return r
    return None


_SHARED_CACHE: dict = {}


def _shared_motion_sets(disc, archive_names: list[str]):
    """Load skeleton+motions from MOT_*.MRG archives on the disc."""
    out = []
    if disc is None:
        return out
    for an in archive_names:
        key = (id(disc), an)
        if key not in _SHARED_CACHE:
            try:
                b = assets.load_bundle(disc.read("BIN.CVM/" + an), an)
            except Exception as e:
                print("[Macross SDF] cannot load", an, e)
                b = None
            _SHARED_CACHE[key] = b
        if _SHARED_CACHE[key] is not None:
            out.append(_SHARED_CACHE[key])
    return out


_SKELETON_LIBRARY: dict = {}


def skeleton_library(disc):
    """All skeletons on the disc (MOT_*.MRG plus .bon files inside *_AC.CMP)."""
    if disc is None:
        return []
    key = id(disc)
    if key not in _SKELETON_LIBRARY:
        out = []
        for f in disc.list():
            base = f.split("/")[-1].upper()
            if not (base.startswith("MOT_") or base.endswith("AMD_AC.CMP")):
                continue
            try:
                b = assets.load_bundle(disc.read(f), base)
            except Exception:
                continue
            out += b.skeletons
        _SKELETON_LIBRARY[key] = out
    return _SKELETON_LIBRARY[key]


def _pick_lods(models: list[assets.ModelEntry], mode: str) -> list[assets.ModelEntry]:
    if mode == "ALL":
        return models
    has_l = any(m.lod == "l" for m in models)
    out = []
    for m in models:
        if m.lod in ("m", "s") and has_l:
            continue
        out.append(m)
    return out


def _motion_bindings(ctx, entry: assets.ModelEntry, bundle: assets.Bundle, shared: list):
    """Return [(MotionEntry, Skeleton|None)] that can drive this model."""
    model = entry.model
    names = assets.node_names(model)
    skeletons = list(bundle.skeletons)
    motions = [(m, bundle) for m in bundle.motions]
    for sb in shared:
        skeletons += sb.skeletons
        motions += [(m, sb) for m in sb.motions]
    out = []
    for me, owner in motions:
        try:
            mot = me.motion
        except Exception as e:
            ctx.warn(f"motion {me.name}: {e}")
            continue
        cands = [s for s in skeletons if len(s.skeleton.bones) == mot.bone_count]
        best, score = assets.best_skeleton(cands, model)
        if (best is None or score < 0.6) and ctx.disc is not None:
            lib = [s for s in skeleton_library(ctx.disc) if len(s.skeleton.bones) == mot.bone_count]
            b2, s2 = assets.best_skeleton(lib, model)
            if s2 > score:
                best, score = b2, s2
        if best is not None and score >= 0.6:
            out.append((me, best.skeleton))
        elif mot.bone_count == len(model.nodes) and (best is None or all(n.startswith("node_") for n in names)):
            # nameless (0100) models: the motion indexes model nodes directly
            out.append((me, None))
    return out


def import_bundle(data: bytes, name: str, options: build.Options, disc=None, source_path: str = ""):
    bundle = assets.load_bundle(data, name)
    ctx = build.ImportContext(bundle, options, disc)
    if options.color_variant and disc is not None:
        try:
            vb = assets.load_bundle(disc.read(options.color_variant), options.color_variant)
            ctx.extra_textures = dict(vb.textures)
        except Exception as e:
            ctx.warn(f"colour variant {options.color_variant}: {e}")
    root = _new_collection(re.sub(r"\.(CMP|MRG|MSD|BIN)$", "", name, flags=re.I))
    root["gfx_source"] = source_path or name
    ctx.collection = root
    if bundle.stage is not None:
        import_stage(ctx, root)
    else:
        import_models(ctx, root, name)
    scn = bpy.context.scene
    scn.render.fps = 60
    return root, ctx


def import_models(ctx: build.ImportContext, root, file_name: str):
    b = ctx.bundle
    o = ctx.options
    shared = _shared_motion_sets(ctx.disc, assets.motion_archives_for(file_name)) \
        if (o.shared_motions and o.import_motions) else []
    entries = _pick_lods(b.models, o.lods)
    # group by parent archive path so AUTH scenes keep their per-actor structure
    first_rigged = None
    for e in entries:
        model = e.model
        if not any(n.mesh is not None for n in model.nodes):
            continue
        col = _new_collection(re.sub(r"\.mdl$", "", e.name), root)
        col["gfx_path"] = e.path
        bindings = _motion_bindings(ctx, e, b, shared) if o.import_motions else []
        rig = o.rig == "ARMATURE" or (o.rig == "AUTO" and (len(model.nodes) > 1 and
                                                         (bindings or model.version == "0200")))
        mesh_obj, arm_obj = build.import_model(ctx, e, col, rig, bindings)
        if e.lod in ("m", "s"):
            lc = _layer_collection(col)
            if lc:
                lc.hide_viewport = True
            col.hide_render = True
        if arm_obj is not None and first_rigged is None:
            first_rigged = arm_obj
    # frame range from first action
    if first_rigged is not None and first_rigged.animation_data and first_rigged.animation_data.action:
        a = first_rigged.animation_data.action
        bpy.context.scene.frame_start = int(a.frame_range[0])
        bpy.context.scene.frame_end = int(a.frame_range[1])


def import_stage(ctx: build.ImportContext, root):
    b = ctx.bundle
    o = ctx.options
    lay = b.stage
    cache: dict = {}
    s = o.scale
    by_stem = {assets.stem(m.name): m for m in b.models}

    def find(prefix: str, lod: str):
        for cand in (f"{prefix}_{lod}_0", f"{prefix}_{lod.upper()}_0"):
            m = by_stem.get(cand.lower())
            if m:
                return m
        return None

    # fixed scenery / sky / bottom
    fixed_col = _new_collection("fixed", root)
    for m in b.models:
        st = assets.stem(m.name)
        if re.match(r"^(gv|obj)_", st) or m.lod in ("m", "s"):
            continue
        me = build.static_mesh(ctx, m, cache)
        if me is not None:
            obj = bpy.data.objects.new(re.sub(r"\.mdl$", "", m.name), me)
            fixed_col.objects.link(obj)
            obj["gfx_source"] = m.path
            if st.startswith("gsky"):
                obj.visible_shadow = False
    if lay is None or not lay.side:
        return
    tiles_col = _new_collection("ground_tiles", root)
    objs_col = _new_collection("objects", root)
    side = lay.side
    cell = lay.cell_size
    pattern = min(max(0, o.stage_pattern), max(lay.pattern_count - 1, 0))
    tiles = lay.tile_grid(pattern)
    arrs = lay.arr_grid(pattern)
    blocks = max(1, int(o.stage_blocks))
    half = (blocks - 1) // 2
    for by in range(-half, blocks - half):
        for bx in range(-half, blocks - half):
            for r in range(side):
                for c in range(side):
                    idx = r * side + c
                    cx = (c - (side - 1) / 2.0 + bx * side) * cell
                    cz = (r - (side - 1) / 2.0 + by * side) * cell
                    cell_m = np.eye(4)
                    cell_m[0, 3], cell_m[2, 3] = cx, cz
                    tid = tiles[idx] if idx < len(tiles) else 0
                    if tid:
                        m = find(f"gv_{tid:02d}", o.stage_lod)
                        if m:
                            me = build.static_mesh(ctx, m, cache)
                            if me is not None:
                                ob = build.place_object(f"tile_{r}_{c}_gv{tid:02d}", me, tiles_col, cell_m, s)
                                ob["gfx_cell"] = [r, c, bx, by]
                    aid = arrs[idx] if idx < len(arrs) else 0
                    if aid and aid - 1 < len(lay.arrangements):
                        for k, pl in enumerate(lay.arrangements[aid - 1]):
                            m = find(f"obj_{pl.obj_id:02d}", o.stage_lod)
                            if not m:
                                continue
                            me = build.static_mesh(ctx, m, cache)
                            if me is None:
                                continue
                            lm = mu.trs(np.array(pl.translation), np.array(pl.rotation), np.array(pl.scale))
                            ob = build.place_object(f"obj{pl.obj_id:02d}_{r}_{c}_{k}", me, objs_col, cell_m @ lm, s)
                            ob["gfx_arrangement"] = aid
    root["gfx_stage_side"] = side
    root["gfx_stage_cell"] = cell
    root["gfx_stage_pattern"] = pattern
    root["gfx_stage_patterns"] = lay.pattern_count
    root["gfx_tile_grid"] = list(tiles)
    root["gfx_arr_grid"] = list(arrs)


def open_disc(path: str):
    return iso.GameDisc(path)


def model_from_armature(arm_obj):
    """Rebuild a minimal gfx2obj.Model (hierarchy + rest TRS) from an imported rig."""
    from ..formats import gfx2obj as g
    bones = list(arm_obj.data.bones)
    bones.sort(key=lambda b: b.get("gfx_node_index", 0))
    index = {b.name: i for i, b in enumerate(bones)}
    nodes = []
    for i, b in enumerate(bones):
        nodes.append(g.Node(i, b.name, tuple(b.get("gfx_rest_translation", (0, 0, 0))),
                            tuple(b.get("gfx_rest_rotation", (0, 0, 0))), tuple(b.get("gfx_rest_scale", (1, 1, 1))),
                            -1, -1, -1, -1, index[b.parent.name] if b.parent else -1))
    return g.Model("rig", [], [], [], nodes), [b.name for b in bones]


def apply_motions_to_rig(arm_obj, data: bytes, name: str, options: build.Options, disc=None):
    """Import every clip in an archive onto an existing Macross SDF armature."""
    bundle = assets.load_bundle(data, name)
    ctx = build.ImportContext(bundle, options, disc)
    model, bone_names = model_from_armature(arm_obj)
    entry = assets.ModelEntry(arm_obj.name, "", b"")
    entry._parsed = model
    shared = _shared_motion_sets(disc, assets.motion_archives_for(name)) if options.shared_motions else []
    bindings = _motion_bindings(ctx, entry, bundle, shared)
    world = build.model_rest_world(model)
    world_b = mu.C4 @ world @ mu.C4_INV
    actions = []
    for me_entry, skel in bindings:
        try:
            actions.append(build.build_action(ctx, arm_obj, bone_names, model, world_b, me_entry.motion, skel,
                                              me_entry.name, options.scale))
        except Exception as e:
            ctx.warn(f"motion {me_entry.name}: {e}")
    build.attach_actions(arm_obj, actions)
    if not bindings:
        ctx.warn("no clip in this archive matches the selected rig's skeleton")
    return ctx, len(actions)
