"""Parse every archive on the disc without Blender and report format coverage.

    python tools/survey_disc.py "F:/.../Chou Jikuu Yousai Macross (Japan).iso" [--json out.json]

Checks: CRICMP/MRG expansion, every GFX2OBJ (incl. mesh decode), every TIM2,
every .bon/.mot.  Prints leaf counts, mesh layouts and any failures.
"""

import argparse
import collections
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from io_import_macross_sdf.formats import gfx2obj, iso, motion, mrg, tim2  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("iso")
    p.add_argument("--json")
    a = p.parse_args()
    t0 = time.time()
    d = iso.GameDisc(a.iso)
    kinds = collections.Counter()
    layouts = collections.Counter()
    versions = collections.Counter()
    failures = []
    stats = collections.Counter()
    for path in d.list():
        up = path.upper()
        if up.startswith(("ADXJ", "MOV")) or up.endswith((".ELF", ".IMG", ".CNF", ".DIR", ".05", ".CVM")):
            continue
        try:
            tree = mrg.build_tree(d.read(path), path.split("/")[-1])
        except Exception as e:
            failures.append((path, "tree", repr(e)))
            continue
        for n in tree.walk():
            kinds[n.kind] += 1
            where = f"{path}::{n.path}"
            try:
                if n.kind == "gfx2obj":
                    m = gfx2obj.parse(n.data)
                    versions[m.version] += 1
                    for w in m.warnings:
                        failures.append((where, "mesh", w))
                    for nd in m.nodes:
                        if nd.mesh is not None:
                            layouts[(hex(nd.mesh.fmt), "indexed" if nd.mesh.indexed else "direct")] += 1
                            stats["vertices"] += len(nd.mesh.positions)
                            stats["triangles"] += len(nd.mesh.faces)
                elif n.kind == "tim2":
                    for pic in tim2.parse(n.data):
                        stats["swizzled" if pic.swizzled else "linear"] += 1
                elif n.kind == "mot":
                    mo = motion.parse_mot(n.data)
                    stats["tracks"] += len(mo.tracks)
                    if mo.footer[:2] != b"\x01\x20":
                        failures.append((where, "mot", "unexpected footer " + mo.footer[:4].hex()))
                elif n.kind == "bon":
                    stats["bones"] += len(motion.parse_bon(n.data).bones)
            except Exception as e:
                failures.append((where, n.kind, repr(e)))
    out = {"seconds": round(time.time() - t0, 1), "leaf_kinds": dict(kinds), "model_versions": dict(versions),
           "mesh_layouts": {f"{k[0]} {k[1]}": v for k, v in layouts.items()}, "stats": dict(stats),
           "failures": failures}
    print(json.dumps({k: v for k, v in out.items() if k != "failures"}, indent=1))
    print(f"failures: {len(failures)}")
    for f in failures[:40]:
        print("  ", f)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1)


if __name__ == "__main__":
    main()
