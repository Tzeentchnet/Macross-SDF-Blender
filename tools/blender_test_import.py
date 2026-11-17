"""Headless Blender test: import assets from the disc, save .blend + preview renders.

Usage (from a shell):

    blender -b --factory-startup --python tools/blender_test_import.py -- \
        --iso "F:/Recomp_GameSource/Chou Jikuu Yousai Macross (Japan).iso" \
        --out "E:/tests/macross_sdf" BIN.CVM/VF1J_AC.CMP BIN.CVM/GD_01.CMP ...

Per asset this writes ``<out>/<NAME>.blend``, ``<out>/<NAME>.png`` (rest pose)
and, for rigged assets, ``<out>/<NAME>__<action>_fNNN.png`` frames.
A ``report.json`` with counts/warnings/timings is updated after each asset.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import traceback

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import io_import_macross_sdf as addon  # noqa: E402
from io_import_macross_sdf.blender import build, importer  # noqa: E402


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--iso", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--blocks", type=int, default=1)
    p.add_argument("--res", type=int, default=768)
    p.add_argument("--engine", default="EEVEE")
    p.add_argument("--lods", default="HIGHEST")
    p.add_argument("--variant", default="")
    p.add_argument("--frames", type=int, default=3, help="frames to render per action (0 = none)")
    p.add_argument("--max-actions", type=int, default=3)
    p.add_argument("--max-models", type=int, default=6)
    p.add_argument("--views", default="persp", help="comma list of persp,front,side,top,back")
    p.add_argument("--actions", default="", help="comma separated action name filter for preview renders")
    p.add_argument("--no-render", action="store_true")
    p.add_argument("--apply-motions", default="", help="disc archive whose clips are applied to every imported rig")
    p.add_argument("assets", nargs="+")
    return p.parse_args(argv)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def scene_bounds(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    mn = Vector((1e30, 1e30, 1e30))
    mx = Vector((-1e30, -1e30, -1e30))
    found = False
    for o in objs:
        if o.type != "MESH" or o.hide_render:
            continue
        if not o.visible_get():
            continue
        oe = o.evaluated_get(dg)
        for c in oe.bound_box:
            w = oe.matrix_world @ Vector(c)
            mn = Vector(map(min, mn, w))
            mx = Vector(map(max, mx, w))
            found = True
    return (mn, mx) if found else (Vector((-1, -1, -1)), Vector((1, 1, 1)))


def setup_render(engine: str, res: int):
    scn = bpy.context.scene
    ok = False
    for e in ([engine] if engine != "EEVEE" else ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"]):
        try:
            scn.render.engine = e
            ok = True
            break
        except TypeError:
            continue
    if not ok:
        scn.render.engine = "BLENDER_WORKBENCH"
    scn.render.resolution_x = res
    scn.render.resolution_y = res
    scn.render.film_transparent = False
    world = bpy.data.worlds.new("preview_world")
    world.color = (0.18, 0.2, 0.24)
    try:
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        bg.inputs[0].default_value = (0.35, 0.38, 0.45, 1.0)
        bg.inputs[1].default_value = 0.8
    except Exception:
        pass
    scn.world = world
    if scn.render.engine == "BLENDER_WORKBENCH":
        scn.display.shading.light = "STUDIO"
        scn.display.shading.color_type = "TEXTURE"


VIEWS = {
    "persp": Vector((0.85, -1.25, 0.6)),
    "front": Vector((0.0, -1.0, 0.05)),
    "side": Vector((1.0, 0.0, 0.05)),
    "top": Vector((0.0, -0.02, 1.0)),
    "back": Vector((-0.6, 1.0, 0.45)),
}


def add_camera_and_light(objs, stage=False, view="persp"):
    mn, mx = scene_bounds(objs)
    ctr = (mn + mx) / 2
    size = max((mx - mn).length, 0.01)
    cam_data = bpy.data.cameras.new("preview_cam")
    cam_data.clip_start = max(size * 0.0005, 0.01)
    cam_data.clip_end = size * 20
    cam = bpy.data.objects.new("preview_cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    if stage:
        # top-down-ish oblique view of the play area
        d = Vector((0.0, -0.9, 1.25)).normalized()
        dist = size * 0.75
    else:
        d = VIEWS[view].normalized()
        dist = size * 1.15
    cam.location = ctr + d * dist
    cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.lens = 40
    bpy.context.scene.camera = cam
    sun_data = bpy.data.lights.new("preview_sun", "SUN")
    sun_data.energy = 3.0
    sun_data.use_shadow = not stage
    sun = bpy.data.objects.new("preview_sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(35))
    bpy.context.scene.collection.objects.link(sun)
    return cam


def render(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def stage_focus_objects(root):
    """For stages, frame the tile grid + objects rather than the 100 km sky."""
    objs = []
    for c in root.children:
        if c.name.startswith(("ground_tiles", "objects")):
            objs += list(c.all_objects)
    return objs or list(root.all_objects)


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    report_path = os.path.join(a.out, "report.json")
    report = {}
    if os.path.exists(report_path):
        try:
            report = json.load(open(report_path))
        except Exception:
            report = {}
    for asset in a.assets:
        name = asset.split("/")[-1].split(".")[0] + (f"__{a.variant.split('/')[-1].split('.')[0]}" if a.variant else "")
        entry = {"asset": asset, "ok": False}
        t0 = time.time()
        try:
            reset_scene()
            try:
                addon.unregister()
            except Exception:
                pass
            addon.register()
            disc = addon.get_disc(a.iso)
            opts = build.Options(lods=a.lods, stage_blocks=a.blocks, color_variant=a.variant)
            root, ctx = importer.import_bundle(disc.read(asset), asset.split("/")[-1], opts, disc, asset)
            entry["import_seconds"] = round(time.time() - t0, 2)
            if a.apply_motions:
                for arm in [o for o in root.all_objects if o.type == "ARMATURE"]:
                    c2, n = importer.apply_motions_to_rig(arm, disc.read(a.apply_motions),
                                                          a.apply_motions.split("/")[-1], build.Options(), disc)
                    entry.setdefault("applied", {})[arm.name] = n
            meshes = [o for o in root.all_objects if o.type == "MESH"]
            arms = [o for o in root.all_objects if o.type == "ARMATURE"]
            entry["mesh_objects"] = len(meshes)
            entry["armatures"] = len(arms)
            entry["triangles"] = sum(len(o.data.polygons) for o in meshes if o.data)
            entry["unique_meshes"] = len({o.data.name for o in meshes})
            entry["images"] = len([i for i in bpy.data.images if i.name not in ("Render Result",)])
            entry["materials"] = len(bpy.data.materials)
            entry["actions"] = sorted(a_.name for a_ in bpy.data.actions)
            entry["warnings"] = ctx.report[:50]
            stage = ctx.bundle.stage is not None
            entry["stage"] = stage
            blend = os.path.join(a.out, name + ".blend")
            if not a.no_render:
                setup_render(a.engine, a.res)
                for arm in arms:
                    if arm.animation_data:
                        arm.animation_data.action = None
                bpy.context.scene.frame_set(0)
                renders = []
                if stage:
                    cam = add_camera_and_light(stage_focus_objects(root), True)
                    render(os.path.join(a.out, name + ".png"))
                    renders.append(name + ".png")
                else:
                    # one render per model collection, others hidden
                    cols = [c for c in root.children if any(o.type == "MESH" for o in c.all_objects)]
                    for col in cols[: a.max_models]:
                        for c2 in cols:
                            c2.hide_render = c2 is not col
                        for o in list(bpy.data.objects):
                            if o.name.startswith("preview_"):
                                bpy.data.objects.remove(o)
                        for view in a.views.split(","):
                            for o in list(bpy.data.objects):
                                if o.name.startswith("preview_"):
                                    bpy.data.objects.remove(o)
                            add_camera_and_light(list(col.all_objects), False, view)
                            fn = f"{name}__{col.name}__{view}.png"
                            render(os.path.join(a.out, fn))
                            renders.append(fn)
                    for c2 in cols:
                        c2.hide_render = False
                # action previews on the first rigged object that has actions
                shots = []
                for arm in arms:
                    ad = arm.animation_data
                    if not ad or not ad.nla_tracks:
                        continue
                    owner = [c for c in root.children if arm.name in c.all_objects]
                    cols = [c for c in root.children if any(o.type == "MESH" for o in c.all_objects)]
                    for c2 in cols:
                        c2.hide_render = bool(owner) and c2 is not owner[0]
                    for o in list(bpy.data.objects):
                        if o.name.startswith("preview_"):
                            bpy.data.objects.remove(o)
                    add_camera_and_light(list(owner[0].all_objects) if owner else list(root.all_objects), False)
                    tracks = list(ad.nla_tracks)
                    if a.actions:
                        want = [w.strip().lower() for w in a.actions.split(",")]
                        tracks = [t for t in tracks if any(w in t.name.lower() for w in want)]
                    if not tracks:
                        continue
                    for tr in tracks[: a.max_actions]:
                        act = tr.strips[0].action
                        ad.action = act
                        try:
                            ad.action_slot = tr.strips[0].action_slot
                        except Exception:
                            pass
                        f0, f1 = act.frame_range
                        n = max(1, a.frames)
                        for k in range(n):
                            f = int(round(f0 + (f1 - f0) * (k / max(n - 1, 1))))
                            bpy.context.scene.frame_set(f)
                            p = os.path.join(a.out, f"{name}__{arm.name}__{act.name}_f{f:03d}.png")
                            render(p)
                            shots.append(os.path.basename(p))
                    ad.action = None
                    if not a.actions:
                        break
                entry["renders"] = renders + shots
            bpy.context.scene.frame_set(0)
            bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
            entry["blend"] = blend
            entry["ok"] = True
        except Exception as e:
            entry["error"] = f"{e}"
            entry["traceback"] = traceback.format_exc()
            traceback.print_exc()
        entry["seconds"] = round(time.time() - t0, 2)
        report[name] = entry
        with open(report_path, "w") as fh:
            json.dump(report, fh, indent=2)
        print("RESULT", name, json.dumps({k: v for k, v in entry.items() if k not in ("traceback",)})[:600])


if __name__ == "__main__":
    main()
