"""Blender adapter: neutral parsed data -> Blender datablocks.

All heavy lifting is numpy + ``foreach_set``; no per-vertex Python loops.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import bpy
import numpy as np
from bpy_extras import anim_utils
from mathutils import Matrix

from ..formats import assets, gfx2obj, motion, pose
from . import mathutil as mu


@dataclass
class Options:
    lods: str = "HIGHEST"            # HIGHEST | ALL
    rig: str = "AUTO"                # AUTO | ARMATURE | NONE
    import_motions: bool = True
    shared_motions: bool = True      # pull skeleton/motions from MOT_*.MRG on the disc
    scale: float = 1.0
    texture_filter: str = "Linear"   # Linear | Closest
    stage_blocks: int = 1            # 1 = one pattern block, 3 = 3x3 (as the game draws)
    stage_lod: str = "l"
    stage_pattern: int = 0           # which GRD_PatTbl layout to build
    color_variant: str = ""          # disc path of a *_COL_nn.MRG texture set
    merge_vertices: bool = True


@dataclass
class ImportContext:
    bundle: assets.Bundle
    options: Options
    disc: object = None              # iso.GameDisc or None
    images: dict = field(default_factory=dict)
    materials: dict = field(default_factory=dict)
    report: list = field(default_factory=list)
    collection: bpy.types.Collection | None = None
    extra_textures: dict = field(default_factory=dict)   # stem -> TIM2 bytes (colour variants)

    def warn(self, msg):
        self.report.append(msg)
        print("[Macross SDF]", msg)


# ---------------------------------------------------------------------------
# Textures

def get_image(ctx: ImportContext, tex_name: str):
    key = assets.stem(tex_name)
    if key in ctx.images:
        return ctx.images[key]
    pic = None
    if key in ctx.extra_textures:
        from ..formats import tim2
        try:
            pic = tim2.parse(ctx.extra_textures[key])[0]
        except Exception as e:  # pragma: no cover
            ctx.warn(f"colour variant texture {key}: {e}")
    if pic is None:
        pic = ctx.bundle.picture(tex_name)
    if pic is None:
        ctx.warn(f"texture '{tex_name}' not found in bundle")
        ctx.images[key] = None
        return None
    img = bpy.data.images.new(tex_name, pic.width, pic.height, alpha=True)
    # Blender stores rows bottom-up; TIM2 is top-down.
    px = np.ascontiguousarray(pic.rgba[::-1], dtype=np.float32) / 255.0
    img.pixels.foreach_set(px.ravel())
    img.alpha_mode = "STRAIGHT"
    try:
        img.file_format = "PNG"
        img.pack()
    except Exception as e:  # pragma: no cover - packing is best effort
        ctx.warn(f"could not pack image {tex_name}: {e}")
    img["tim2_image_type"] = pic.image_type
    img["tim2_clut_type"] = pic.clut_type
    img["tim2_tex0"] = f"0x{pic.tex0:016X}"
    img["tim2_swizzled"] = bool(pic.swizzled)
    img["tim2_mipmaps"] = pic.mipmaps
    a = pic.rgba[..., 3]
    img["has_alpha"] = bool((a < 250).any())
    img["has_partial_alpha"] = bool(((a > 8) & (a < 247)).any())
    ctx.images[key] = img
    return img


# ---------------------------------------------------------------------------
# Materials

def _link(nt, a, b):
    nt.links.new(a, b)


def get_material(ctx: ImportContext, model: gfx2obj.Model, mat_index: int, lit: bool, batches_info):
    gm = model.materials[mat_index] if 0 <= mat_index < len(model.materials) else None
    tex_name = model.textures[gm.texture] if gm is not None and 0 <= gm.texture < len(model.textures) else ""
    kind = gm.kind if gm is not None else 0
    key = (assets.stem(tex_name), kind, lit)
    if key in ctx.materials:
        return ctx.materials[key]
    img = get_image(ctx, tex_name) if tex_name else None
    name = f"{tex_name or 'untextured'}{'' if lit else '_unlit'}"
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (900, 0)

    col_attr = nt.nodes.new("ShaderNodeAttribute")
    col_attr.attribute_name = "gfx_color"
    col_attr.location = (-500, -150)

    if img is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.interpolation = ctx.options.texture_filter
        tex.location = (-500, 200)
        tex_col, tex_alpha = tex.outputs["Color"], tex.outputs["Alpha"]
    else:
        rgb = nt.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = (0.8, 0.8, 0.8, 1.0)
        rgb.location = (-500, 200)
        tex_col, tex_alpha = rgb.outputs[0], None

    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    mul.location = (-200, 150)
    _link(nt, tex_col, mul.inputs[6])
    _link(nt, col_attr.outputs["Color"], mul.inputs[7])

    alpha_socket = None
    if tex_alpha is not None:
        am = nt.nodes.new("ShaderNodeMath")
        am.operation = "MULTIPLY"
        am.location = (-200, -150)
        _link(nt, tex_alpha, am.inputs[0])
        _link(nt, col_attr.outputs["Alpha"], am.inputs[1])
        alpha_socket = am.outputs[0]

    if lit:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (300, 100)
        _link(nt, mul.outputs[2], bsdf.inputs["Base Color"])
        emit_attr = nt.nodes.new("ShaderNodeAttribute")
        emit_attr.attribute_name = "gfx_emit"
        emit_attr.location = (-500, -400)
        emul = nt.nodes.new("ShaderNodeMix")
        emul.data_type = "RGBA"
        emul.blend_type = "MULTIPLY"
        emul.inputs["Factor"].default_value = 1.0
        emul.location = (-200, -400)
        _link(nt, tex_col, emul.inputs[6])
        _link(nt, emit_attr.outputs["Color"], emul.inputs[7])
        _link(nt, emul.outputs[2], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0
        spec_power, spec_level = batches_info
        # Phong exponent -> roughness (Beckmann-style approximation)
        rough = math.sqrt(2.0 / (spec_power + 2.0)) if spec_power > 0 else 0.8
        bsdf.inputs["Roughness"].default_value = min(max(rough, 0.05), 1.0)
        bsdf.inputs["Specular IOR Level"].default_value = min(max(spec_level, 0.0), 1.0) * 0.5
        if alpha_socket is not None:
            _link(nt, alpha_socket, bsdf.inputs["Alpha"])
        _link(nt, bsdf.outputs[0], out.inputs["Surface"])
    else:
        emis = nt.nodes.new("ShaderNodeEmission")
        emis.location = (300, 100)
        _link(nt, mul.outputs[2], emis.inputs["Color"])
        if alpha_socket is not None:
            transp = nt.nodes.new("ShaderNodeBsdfTransparent")
            transp.location = (300, -100)
            mix = nt.nodes.new("ShaderNodeMixShader")
            mix.location = (600, 0)
            _link(nt, alpha_socket, mix.inputs[0])
            _link(nt, transp.outputs[0], mix.inputs[1])
            _link(nt, emis.outputs[0], mix.inputs[2])
            _link(nt, mix.outputs[0], out.inputs["Surface"])
        else:
            _link(nt, emis.outputs[0], out.inputs["Surface"])

    # Blending: GFX2 material kind 1 is used for translucent parts (canopies,
    # effects); textures with cut-out alpha use dithered (alpha-test-like).
    translucent = kind == 1 or "_tra_" in f"_{tex_name.lower()}_"
    has_alpha = bool(img is not None and img.get("has_alpha"))
    try:
        if translucent and has_alpha:
            mat.surface_render_method = "BLENDED"
        else:
            mat.surface_render_method = "DITHERED"
    except Exception:
        pass
    mat.use_backface_culling = False
    if img is not None:
        mat.diffuse_color = (0.8, 0.8, 0.8, 1.0)
    if gm is not None:
        mat["gfx_material_index"] = gm.index
        mat["gfx_material_kind"] = gm.kind
        mat["gfx_material_raw"] = " ".join(f"{int(x):08X}" for x in gm.raw)
        mat["gfx_uv_region"] = list(gm.uv_region)
    mat["gfx_texture"] = tex_name
    mat["gfx_lit"] = lit
    ctx.materials[key] = mat
    return mat


# ---------------------------------------------------------------------------
# Geometry

@dataclass
class Geometry:
    positions: np.ndarray          # (V,3) blender space (rest pose / world)
    faces: np.ndarray              # (F,3)
    corner_uv: np.ndarray | None   # (F*3,2)
    corner_normal: np.ndarray | None
    corner_color: np.ndarray       # (F*3,4)
    corner_emit: np.ndarray        # (F*3,4)
    face_mat: np.ndarray           # (F,) material slot
    vert_node: np.ndarray          # (V,) node index
    materials: list
    has_normals: bool


def model_rest_world(model: gfx2obj.Model) -> np.ndarray:
    n = len(model.nodes)
    if n == 0:
        return np.zeros((0, 4, 4))
    t = np.array([nd.translation for nd in model.nodes])
    r = np.array([nd.rotation for nd in model.nodes])
    s = np.array([nd.scale for nd in model.nodes])
    local = mu.trs(t, r, s)
    return mu.world_from_local(local, [nd.parent for nd in model.nodes])


def build_geometry(ctx: ImportContext, model: gfx2obj.Model, world: np.ndarray, scale: float) -> Geometry | None:
    P, F, UV, N, COL, EMI, FM, VN = [], [], [], [], [], [], [], []
    mats: list = []
    mat_slot: dict = {}
    base = 0
    any_normals = False
    for nd in model.nodes:
        m = nd.mesh
        if m is None or len(m.faces) == 0:
            continue
        # vertices are game-local: blender = C @ W_game @ v  (bones use C W C^-1)
        W = mu.C4 @ world[nd.index]
        pos = m.positions.astype(np.float64) @ W[:3, :3].T + W[:3, 3]
        pos *= scale
        faces = m.faces.astype(np.int64)
        nrm = None
        if m.normals is not None:
            nm = np.linalg.inv(W[:3, :3]).T
            nrm = m.normals.astype(np.float64) @ nm.T
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = np.where(ln > 1e-12, nrm / np.maximum(ln, 1e-12), np.array([0.0, 0.0, 1.0]))
            any_normals = True
        # per-vertex batch colours
        nb = len(m.batches)
        bcol = np.array([b.colors for b in m.batches], np.float64).reshape(nb, 3, 4) if nb else np.zeros((0, 3, 4))
        # corner arrays
        cidx = faces.reshape(-1)
        fb = np.repeat(m.face_batch, 3)
        if m.colors is not None and nrm is None:
            col = m.colors[cidx].astype(np.float64) / 128.0
            col[:, 3] = np.minimum(col[:, 3], 1.0)
            emi = np.zeros_like(col)
        elif nb:
            col = bcol[fb, 1] / 255.0
            col[:, 3] = 1.0
            emi = bcol[fb, 0] / 255.0
            emi[:, 3] = 1.0
        else:
            col = np.ones((len(cidx), 4))
            emi = np.zeros((len(cidx), 4))
        lit = nrm is not None
        # material slot
        spec = np.array([b.spec_power for b in m.batches]) if nb else np.zeros(1)
        speclvl = (bcol[:, 2, :3].mean() / 255.0) if nb else 0.0
        mkey = (nd.material, lit)
        if mkey not in mat_slot:
            mat_slot[mkey] = len(mats)
            mats.append(get_material(ctx, model, nd.material, lit, (float(spec.mean()), float(speclvl))))
        slot = mat_slot[mkey]

        # orientation: reorient using normals (mirror conversion flips winding)
        v = pos[faces]
        fn = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        if nrm is not None:
            flip = np.einsum("ij,ij->i", fn, nrm[faces].sum(1)) < 0
        else:
            flip = np.full(len(faces), np.linalg.det(W[:3, :3]) < 0)
        faces = faces.copy()
        faces[flip] = faces[flip][:, [0, 2, 1]]
        corner_order = np.arange(len(faces) * 3).reshape(-1, 3)
        corner_order[flip] = corner_order[flip][:, [0, 2, 1]]
        co = corner_order.reshape(-1)
        cidx = faces.reshape(-1)
        col = col[co]
        emi = emi[co]

        # weld duplicated strip vertices (per node) so the mesh is connected
        if ctx.options.merge_vertices:
            key = np.round(pos / max(scale, 1e-9), 5)
            _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
            inv = inv.reshape(-1)
            upos = pos[first]
            ufaces = inv[faces]
        else:
            upos, ufaces = pos, faces
            first = np.arange(len(pos))
        good = (ufaces[:, 0] != ufaces[:, 1]) & (ufaces[:, 1] != ufaces[:, 2]) & (ufaces[:, 0] != ufaces[:, 2])
        gc = np.repeat(good, 3)
        P.append(upos)
        F.append(ufaces[good] + base)
        UV.append(m.uvs[cidx][gc] if m.uvs is not None else np.zeros((gc.sum(), 2)))
        N.append(nrm[cidx][gc] if nrm is not None else None)
        COL.append(col[gc])
        EMI.append(emi[gc])
        FM.append(np.full(good.sum(), slot, np.int32))
        VN.append(np.full(len(upos), nd.index, np.int32))
        base += len(upos)
    if not P:
        return None
    if any_normals:
        N = [x if x is not None else np.tile([0.0, 0.0, 1.0], (len(c), 1)) for x, c in zip(N, COL)]
        corner_normal = np.concatenate(N)
    else:
        corner_normal = None
    uv = np.concatenate(UV).astype(np.float64)
    uv[:, 1] = 1.0 - uv[:, 1]
    return Geometry(np.concatenate(P), np.concatenate(F), uv, corner_normal, np.concatenate(COL),
                    np.concatenate(EMI), np.concatenate(FM), np.concatenate(VN), mats, any_normals)


def make_mesh(name: str, g: Geometry) -> bpy.types.Mesh:
    me = bpy.data.meshes.new(name)
    nv, nf = len(g.positions), len(g.faces)
    me.vertices.add(nv)
    me.vertices.foreach_set("co", g.positions.astype(np.float32).ravel())
    me.loops.add(nf * 3)
    me.loops.foreach_set("vertex_index", g.faces.astype(np.int32).ravel())
    me.polygons.add(nf)
    me.polygons.foreach_set("loop_start", np.arange(0, nf * 3, 3, dtype=np.int32))
    me.update(calc_edges=True)
    for m in g.materials:
        me.materials.append(m)
    me.polygons.foreach_set("material_index", g.face_mat.astype(np.int32))
    uvl = me.uv_layers.new(name="UVMap")
    uvl.uv.foreach_set("vector", g.corner_uv.astype(np.float32).ravel())
    ca = me.color_attributes.new("gfx_color", "FLOAT_COLOR", "CORNER")
    ca.data.foreach_set("color", g.corner_color.astype(np.float32).ravel())
    ea = me.color_attributes.new("gfx_emit", "FLOAT_COLOR", "CORNER")
    ea.data.foreach_set("color", g.corner_emit.astype(np.float32).ravel())
    try:
        me.color_attributes.active_color = ca
        me.color_attributes.render_color_index = 0
    except Exception:
        pass
    if g.corner_normal is not None:
        me.polygons.foreach_set("use_smooth", np.ones(nf, bool))
        me.normals_split_custom_set(g.corner_normal.astype(np.float32).reshape(-1, 3))
    me.validate(clean_customdata=False)
    me.update()
    return me


# ---------------------------------------------------------------------------
# Armature + motions

def unique_names(names: list[str]) -> list[str]:
    seen: dict = {}
    out = []
    for n in names:
        n = (n or "node")[:60]
        if n in seen:
            seen[n] += 1
            out.append(f"{n}.{seen[n]:03d}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def build_armature(ctx: ImportContext, name: str, model: gfx2obj.Model, world_b: np.ndarray,
                   collection, scale: float):
    arm = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm)
    collection.objects.link(obj)
    arm.display_type = "STICK"
    obj.show_in_front = True
    bone_names = unique_names([nd.name for nd in model.nodes])
    pos = world_b[:, :3, 3] * scale
    size = float(np.ptp(pos, axis=0).max()) if len(pos) else 1.0
    length = max(size * 0.03, 0.01)

    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = []
    rot = mu.orthonormalize(world_b[:, :3, :3])
    for i, nd in enumerate(model.nodes):
        eb = arm.edit_bones.new(bone_names[i])
        eb.head = (0.0, 0.0, 0.0)
        eb.tail = (0.0, length, 0.0)
        m = np.eye(4)
        m[:3, :3] = rot[i]
        m[:3, 3] = pos[i]
        eb.matrix = Matrix(m.tolist())
        ebs.append(eb)
    for i, nd in enumerate(model.nodes):
        if nd.parent >= 0:
            ebs[i].parent = ebs[nd.parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = prev_active
    for i, nd in enumerate(model.nodes):
        pb = obj.pose.bones[bone_names[i]]
        pb.rotation_mode = "QUATERNION"
        b = arm.bones[bone_names[i]]
        b["gfx_node_index"] = nd.index
        b["gfx_rest_translation"] = list(nd.translation)
        b["gfx_rest_rotation"] = list(nd.rotation)
        b["gfx_rest_scale"] = list(nd.scale)
    return obj, bone_names


def bone_rest_matrices(arm_obj, bone_names) -> np.ndarray:
    return np.array([np.array(arm_obj.data.bones[n].matrix_local) for n in bone_names])


def _new_action(name: str, arm_obj):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    slot = act.slots.new(id_type="OBJECT", name=arm_obj.name)
    try:
        cb = anim_utils.action_ensure_channelbag_for_slot(act, slot)
    except Exception:
        layer = act.layers.new("Layer")
        strip = layer.strips.new(type="KEYFRAME")
        cb = strip.channelbag(slot, ensure=True)
    return act, slot, cb


def _write_curve(cb, path: str, index: int, frames: np.ndarray, values: np.ndarray, group: str):
    fc = cb.fcurves.new(path, index=index)
    try:
        grp = cb.groups.get(group) or cb.groups.new(group)
        fc.group = grp
    except Exception:
        pass
    n = len(frames)
    fc.keyframe_points.add(n)
    co = np.empty(n * 2, np.float32)
    co[0::2] = frames
    co[1::2] = values
    fc.keyframe_points.foreach_set("co", co)
    try:
        fc.keyframe_points.foreach_set("interpolation", np.ones(n, np.int32))  # LINEAR
    except Exception:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    fc.update()
    return fc


def skeleton_from_model(model: gfx2obj.Model) -> motion.Skeleton:
    """Pseudo skeleton for motions that index model nodes directly."""
    bones = []
    for nd in model.nodes:
        kids = []
        c = nd.child
        guard = 0
        while 0 <= c < len(model.nodes) and guard < len(model.nodes):
            kids.append(c)
            c = model.nodes[c].sibling
            guard += 1
        bones.append(motion.Bone(nd.index, nd.name, 1, nd.index, nd.translation, nd.rotation, nd.scale,
                                 tuple(kids), (), (), nd.parent))
    return motion.Skeleton(bones)


def motion_locals(model: gfx2obj.Model, mot: motion.Motion, skel: motion.Skeleton | None,
                  frames: int) -> tuple[np.ndarray, list[int]]:
    """Per-frame local game matrices for every model node, plus driven node list."""
    n = len(model.nodes)
    rest = mu.trs(np.array([nd.translation for nd in model.nodes], np.float64),
                  np.array([nd.rotation for nd in model.nodes], np.float64),
                  np.array([nd.scale for nd in model.nodes], np.float64))
    local = np.repeat(rest[None], frames, axis=0)
    direct = skel is None
    if direct:
        skel = skeleton_from_model(model)
    bl = pose.evaluate(skel, mot, frames)
    driven = []
    if direct:
        local[:, :, :, :] = bl[:, :n]
        driven = sorted({t.bone for t in mot.tracks if t.bone < n})
    else:
        lookup = {nd.name.lower(): nd.index for nd in model.nodes}
        for bi, b in enumerate(skel.bones):
            ni = lookup.get(b.name.lower())
            if ni is None:
                continue
            local[:, ni] = bl[:, bi]
            driven.append(ni)
    return local, driven


def build_action(ctx: ImportContext, arm_obj, bone_names, model: gfx2obj.Model, world_rest_b: np.ndarray,
                 mot: motion.Motion, skel: motion.Skeleton | None, name: str, scale: float):
    frames = max(mot.frame_count, 1)
    local, driven = motion_locals(model, mot, skel, frames)
    parents = [nd.parent for nd in model.nodes]
    world = mu.world_from_local(local, parents)                   # (F,n,4,4) game
    wb = mu.C4 @ world @ mu.C4_INV                                  # blender
    wb[..., :3, 3] *= scale
    wr = world_rest_b.copy()
    wr[:, :3, 3] *= scale
    B = bone_rest_matrices(arm_obj, bone_names)                     # (n,4,4)
    M = wb @ np.linalg.inv(wr)[None] @ B[None]                      # armature-space pose
    Binv = np.linalg.inv(B)
    basis = np.empty_like(M)
    for i, p in enumerate(parents):
        if p < 0:
            basis[:, i] = Binv[i][None] @ M[:, i]
        else:
            basis[:, i] = (Binv[i] @ B[p])[None] @ np.linalg.inv(M[:, p]) @ M[:, i]
    loc, quat, scl = mu.decompose(basis)
    quat = mu.make_quat_continuous(quat)
    act, slot, cb = _new_action(name, arm_obj)
    fr = np.arange(frames, dtype=np.float32)
    ident_q = np.array([1.0, 0.0, 0.0, 0.0])
    for i, bn in enumerate(bone_names):
        moving = (np.abs(loc[:, i]).max() > 1e-6 or np.abs(np.abs(quat[:, i]) - ident_q).max() > 1e-6
                  or np.abs(scl[:, i] - 1.0).max() > 1e-6)
        if not moving and i not in driven:
            continue
        base = f'pose.bones["{bn}"]'
        for k in range(3):
            _write_curve(cb, base + ".location", k, fr, loc[:, i, k], bn)
        for k in range(4):
            _write_curve(cb, base + ".rotation_quaternion", k, fr, quat[:, i, k], bn)
        if np.abs(scl[:, i] - 1.0).max() > 1e-6:
            for k in range(3):
                _write_curve(cb, base + ".scale", k, fr, scl[:, i, k], bn)
    act.frame_range = (0, max(frames - 1, 1))
    act["gfx_frame_count"] = mot.frame_count
    act["gfx_fps"] = mot.fps
    act["gfx_speed"] = mot.speed
    act["gfx_skeleton_bones"] = mot.bone_count
    return act, slot


def attach_actions(arm_obj, actions):
    if not actions:
        return
    ad = arm_obj.animation_data or arm_obj.animation_data_create()
    had_action = ad.action is not None
    for act, slot in actions:
        tr = ad.nla_tracks.new()
        tr.name = act.name
        st = tr.strips.new(act.name, 0, act)
        try:
            st.action_slot = slot
        except Exception:
            pass
        tr.mute = True
    if had_action:
        return
    act, slot = actions[0]
    ad.action = act
    try:
        ad.action_slot = slot
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Model import

def import_model(ctx: ImportContext, entry: assets.ModelEntry, collection, rig: bool,
                 motions: list = (), skeleton: motion.Skeleton | None = None):
    model = entry.model
    for w in model.warnings:
        ctx.warn(f"{entry.name}: {w}")
    scale = ctx.options.scale
    world = model_rest_world(model)
    name = re.sub(r"\.mdl$", "", entry.name)
    g = build_geometry(ctx, model, world, scale)
    world_b = mu.C4 @ world @ mu.C4_INV if len(world) else world
    mesh_obj = None
    if g is not None:
        me = make_mesh(name, g)
        mesh_obj = bpy.data.objects.new(name, me)
        collection.objects.link(mesh_obj)
        mesh_obj["gfx_source"] = entry.path
        mesh_obj["gfx_version"] = model.version
        mesh_obj["gfx_textures"] = list(model.textures)
    arm_obj = None
    if rig and len(model.nodes) > 1:
        arm_obj, bone_names = build_armature(ctx, name + "_rig", model, world_b, collection, scale)
        arm_obj["gfx_source"] = entry.path
        if mesh_obj is not None:
            mesh_obj.parent = arm_obj
            mod = mesh_obj.modifiers.new("Armature", "ARMATURE")
            mod.object = arm_obj
            groups = [mesh_obj.vertex_groups.new(name=bn) for bn in bone_names]
            for ni in np.unique(g.vert_node):
                idx = np.nonzero(g.vert_node == ni)[0].tolist()
                groups[int(ni)].add(idx, 1.0, "REPLACE")
        actions = []
        for me_entry, skel in motions:
            try:
                act = build_action(ctx, arm_obj, bone_names, model, world_b, me_entry.motion, skel,
                                   f"{me_entry.name}", scale)
                actions.append(act)
            except Exception as e:
                ctx.warn(f"motion {me_entry.name}: {e}")
        attach_actions(arm_obj, actions)
    return mesh_obj, arm_obj


# ---------------------------------------------------------------------------
# Static (stage) helpers

def static_mesh(ctx: ImportContext, entry: assets.ModelEntry, cache: dict):
    key = entry.path
    if key in cache:
        return cache[key]
    model = entry.model
    world = model_rest_world(model)
    g = build_geometry(ctx, model, world, ctx.options.scale)
    me = make_mesh(re.sub(r"\.mdl$", "", entry.name), g) if g is not None else None
    cache[key] = me
    return me


def place_object(name: str, me, collection, m_game: np.ndarray, scale: float):
    obj = bpy.data.objects.new(name, me)
    m = mu.to_blender(m_game)
    m[:3, 3] *= scale
    obj.matrix_world = Matrix(m.tolist())
    collection.objects.link(obj)
    return obj
