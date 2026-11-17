"""Import every importable archive on the disc (no saving) and report failures.

blender -b --factory-startup --python tools/blender_smoke_all.py -- --iso ISO --out report.json [--filter GD_]
"""
import argparse
import json
import os
import sys
import time
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import io_import_macross_sdf as addon  # noqa: E402
from io_import_macross_sdf.blender import build, importer  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
p = argparse.ArgumentParser()
p.add_argument("--iso", required=True)
p.add_argument("--out", required=True)
p.add_argument("--filter", default="")
a = p.parse_args(argv)

addon.register()
disc = addon.get_disc(a.iso)
files = [f for f in disc.list() if f.upper().endswith((".CMP", ".MRG", ".MSD", ".CAT", ".CHRW"))
         and a.filter.upper() in f.upper()]
report = {}
t_all = time.time()
for i, f in enumerate(files):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    t0 = time.time()
    e = {"ok": False}
    try:
        root, ctx = importer.import_bundle(disc.read(f), f.split("/")[-1], build.Options(), disc, f)
        objs = list(root.all_objects)
        e.update(ok=True, meshes=sum(o.type == "MESH" for o in objs), rigs=sum(o.type == "ARMATURE" for o in objs),
                 tris=sum(len(o.data.polygons) for o in objs if o.type == "MESH"),
                 actions=len(bpy.data.actions), images=len(bpy.data.images), warnings=len(ctx.report),
                 first_warnings=ctx.report[:5], stage=ctx.bundle.stage is not None)
    except Exception as ex:
        e["error"] = repr(ex)
        e["traceback"] = traceback.format_exc()
    e["seconds"] = round(time.time() - t0, 2)
    report[f] = e
    print(f"[{i + 1}/{len(files)}] {f} {'OK' if e['ok'] else 'FAIL ' + e.get('error', '')} {e['seconds']}s", flush=True)
summary = {"files": len(files), "ok": sum(r["ok"] for r in report.values()),
           "failed": [k for k, r in report.items() if not r["ok"]], "seconds": round(time.time() - t_all, 1)}
json.dump({"summary": summary, "files": report}, open(a.out, "w"), indent=1)
print("SUMMARY", json.dumps(summary))
