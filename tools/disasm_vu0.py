"""Annotate VU0 macro-mode (COP2) instructions in the recomp's disassembly.

The SDF_Macross ``tools/disasm_elf.py`` leaves COP2 macro instructions as
``.word``.  This wrapper runs it and replaces those words with mnemonics:

    python tools/disasm_vu0.py <SDF_Macross>/tools/disasm_elf.py <ELF> <symbol> [--instructions N]
"""

import re
import subprocess
import sys

BC = "xyzw"
SP1 = {}
for i, base in enumerate(["vadd", "vsub", "vmadd", "vmsub", "vmax", "vmini", "vmul"]):
    for k in range(4):
        SP1[i * 4 + k] = (base + BC[k], "bc")
SP1.update({0x1C: ("vmulq", "q"), 0x1D: ("vmaxi", "i"), 0x1E: ("vmuli", "i"), 0x1F: ("vminii", "i"),
            0x20: ("vaddq", "q"), 0x21: ("vmaddq", "q"), 0x22: ("vaddi", "i"), 0x23: ("vmaddi", "i"),
            0x24: ("vsubq", "q"), 0x25: ("vmsubq", "q"), 0x26: ("vsubi", "i"), 0x27: ("vmsubi", "i"),
            0x28: ("vadd", "3"), 0x29: ("vmadd", "3"), 0x2A: ("vmul", "3"), 0x2B: ("vmax", "3"),
            0x2C: ("vsub", "3"), 0x2D: ("vmsub", "3"), 0x2E: ("vopmsub", "3"), 0x2F: ("vmini", "3"),
            0x30: ("viadd", "int"), 0x31: ("visub", "int"), 0x32: ("viaddi", "inti"), 0x34: ("viand", "int"),
            0x35: ("vior", "int"), 0x38: ("vcallms", "call"), 0x39: ("vcallmsr", "call")})
SP2 = {}
for i, base in enumerate(["vadda", "vsuba", "vmadda", "vmsuba"]):
    for k in range(4):
        SP2[i * 4 + k] = (base + BC[k], "abc")
for k in range(4):
    SP2[0x18 + k] = ("vmula" + BC[k], "abc")
SP2.update({0x10: ("vitof0", "2"), 0x11: ("vitof4", "2"), 0x12: ("vitof12", "2"), 0x13: ("vitof15", "2"),
            0x14: ("vftoi0", "2"), 0x15: ("vftoi4", "2"), 0x16: ("vftoi12", "2"), 0x17: ("vftoi15", "2"),
            0x1C: ("vmulaq", "aq"), 0x1D: ("vabs", "2"), 0x1E: ("vmulai", "aq"), 0x1F: ("vclipw", "clip"),
            0x20: ("vaddaq", "aq"), 0x21: ("vmaddaq", "aq"), 0x22: ("vaddai", "aq"), 0x23: ("vmaddai", "aq"),
            0x24: ("vsubaq", "aq"), 0x25: ("vmsubaq", "aq"), 0x26: ("vsubai", "aq"), 0x27: ("vmsubai", "aq"),
            0x28: ("vadda", "a3"), 0x29: ("vmadda", "a3"), 0x2A: ("vmula", "a3"), 0x2C: ("vsuba", "a3"),
            0x2D: ("vmsuba", "a3"), 0x2E: ("vopmula", "a3"), 0x2F: ("vnop", "none"), 0x30: ("vmove", "2"),
            0x31: ("vmr32", "2"), 0x34: ("vlqi", "lq"), 0x35: ("vsqi", "lq"), 0x36: ("vlqd", "lq"),
            0x37: ("vsqd", "lq"), 0x38: ("vdiv", "div"), 0x39: ("vsqrt", "sqrt"), 0x3A: ("vrsqrt", "div"),
            0x3B: ("vwaitq", "none"), 0x3C: ("vmtir", "mtir"), 0x3D: ("vmfir", "mfir"), 0x3E: ("vilwr", "lq"),
            0x3F: ("viswr", "lq"), 0x40: ("vrnext", "2"), 0x41: ("vrget", "2"), 0x42: ("vrinit", "2"),
            0x43: ("vrxor", "2")})


def decode(w: int) -> str | None:
    if (w >> 26) != 0x12:
        return None
    if not (w >> 25) & 1:
        rs = (w >> 21) & 0x1F
        rt = (w >> 16) & 0x1F
        rd = (w >> 11) & 0x1F
        names = {1: "qmfc2", 2: "cfc2", 5: "qmtc2", 6: "ctc2"}
        if rs in names:
            return f"{names[rs]} r{rt}, vf{rd}/vi{rd}"
        return None
    dest = "".join(c for i, c in enumerate("xyzw") if (w >> (24 - i)) & 1)
    ft = (w >> 16) & 0x1F
    fs = (w >> 11) & 0x1F
    fd = (w >> 6) & 0x1F
    fn = w & 0x3F
    if fn < 0x3C:
        ent = SP1.get(fn)
        if not ent:
            return f"cop2.sp1 0x{fn:02X}"
        name, kind = ent
        if kind in ("bc", "3"):
            return f"{name}.{dest} vf{fd}, vf{fs}, vf{ft}"
        if kind in ("q", "i"):
            return f"{name}.{dest} vf{fd}, vf{fs}, {kind.upper()}"
        if kind == "int":
            return f"{name} vi{fd}, vi{fs}, vi{ft}"
        if kind == "inti":
            return f"{name} vi{ft}, vi{fs}, {fd}"
        return f"{name} 0x{(w >> 6) & 0x7FFF:X}"
    idx = (((w >> 6) & 0x1F) << 2) | (fn & 3)
    ent = SP2.get(idx)
    if not ent:
        return f"cop2.sp2 0x{idx:02X}"
    name, kind = ent
    fsf = "xyzw"[(w >> 21) & 3]
    ftf = "xyzw"[(w >> 23) & 3]
    if kind == "abc":
        return f"{name}.{dest} ACC, vf{fs}, vf{ft}"
    if kind == "a3":
        return f"{name}.{dest} ACC, vf{fs}, vf{ft}"
    if kind == "aq":
        return f"{name}.{dest} ACC, vf{fs}"
    if kind == "2":
        return f"{name}.{dest} vf{ft}, vf{fs}"
    if kind == "div":
        return f"{name} Q, vf{fs}.{fsf}, vf{ft}.{ftf}"
    if kind == "sqrt":
        return f"{name} Q, vf{ft}.{ftf}"
    if kind == "clip":
        return f"{name}.xyz vf{fs}, vf{ft}.w"
    if kind == "lq":
        return f"{name}.{dest} vf{ft}, vi{fs}"
    if kind == "mtir":
        return f"{name} vi{ft}, vf{fs}.{fsf}"
    if kind == "mfir":
        return f"{name}.{dest} vf{ft}, vi{fs}"
    return name


def main():
    tool, elf, sym = sys.argv[1:4]
    rest = sys.argv[4:]
    out = subprocess.run([sys.executable, tool, elf, sym] + rest, capture_output=True, text=True).stdout
    for line in out.splitlines():
        m = re.search(r"\.word\s+0x([0-9a-fA-F]+)", line)
        if m:
            d = decode(int(m.group(1), 16))
            if d:
                line = line[:m.start()] + d
        m = re.search(r"\b(lqc2|sqc2)\b", line)
        print(line)


if __name__ == "__main__":
    main()
