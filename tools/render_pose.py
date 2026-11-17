"""Render one action/frame of a saved test .blend from several views.

blender -b FILE.blend --python tools/render_pose.py -- --rig NAME --action NAME --frame N --out PREFIX [--views top,side,front]
"""
import sys, os, math, argparse
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
p = argparse.ArgumentParser()
p.add_argument("--rig", required=True)
p.add_argument("--action", required=True)
p.add_argument("--frame", type=int, default=0)
p.add_argument("--out", required=True)
p.add_argument("--views", default="top,side,front,persp")
p.add_argument("--res", type=int, default=512)
a = p.parse_args(argv)
arm = bpy.data.objects[a.rig]
act = bpy.data.actions[a.action]
ad = arm.animation_data
ad.action = act
for tr in ad.nla_tracks:
    if tr.strips and tr.strips[0].action == act:
        try:
            ad.action_slot = tr.strips[0].action_slot
        except Exception:
            pass
scn = bpy.context.scene
scn.frame_set(a.frame)
col = arm.users_collection[0]
for c in bpy.data.collections:
    c.hide_render = not (c == col or col.name in [x.name for x in c.children_recursive] or c in col.children_recursive)
dg = bpy.context.evaluated_depsgraph_get()
mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
for o in col.all_objects:
    if o.type == "MESH":
        oe = o.evaluated_get(dg)
        for v in oe.data.vertices:
            w = oe.matrix_world @ v.co
            mn = Vector(map(min, mn, w)); mx = Vector(map(max, mx, w))
ctr = (mn + mx) / 2; size = (mx - mn).length
cam = scn.camera
D = {"top": Vector((0, -0.001, 1)), "side": Vector((1, 0, 0.001)), "front": Vector((0, -1, 0.001)),
     "persp": Vector((0.85, -1.25, 0.6)), "back": Vector((0, 1, 0.001))}
cam.data.type = "ORTHO"
cam.data.ortho_scale = size * 1.05
cam.data.clip_end = size * 10
scn.render.resolution_x = scn.render.resolution_y = a.res
for v in a.views.split(","):
    cam.location = ctr + D[v].normalized() * size * 2
    cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
    scn.render.filepath = f"{a.out}_{v}.png"
    bpy.ops.render.render(write_still=True)
