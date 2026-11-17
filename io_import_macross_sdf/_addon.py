"""Macross SDF (PS2, SLPM-65405) importer for Blender 5.2.

File > Import > Macross SDF ...
  * Asset file  - an extracted .CMP / .MRG / .MSD / decompressed .bin file
  * Disc image  - pick any model/stage/motion archive straight from the ISO
"""

from __future__ import annotations

import os
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from .blender import build, importer

ADDON_ID = __package__  # package that holds this module (the add-on id)


def prefs():
    try:
        return bpy.context.preferences.addons[ADDON_ID].preferences
    except Exception:
        return None


class MACROSS_SDF_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    iso_path: StringProperty(
        name="Disc image",
        description="Chou Jikuu Yousai Macross (Japan) ISO (SLPM-65405). Used for shared skeletons/motions "
                    "and the 'From Disc' importer",
        subtype="FILE_PATH",
        default="",
    )

    def draw(self, context):
        self.layout.prop(self, "iso_path")


_DISC = {"path": None, "disc": None, "items": []}


def get_disc(path: str):
    if not path or not os.path.isfile(path):
        return None
    if _DISC["path"] != path:
        if _DISC["disc"] is not None:
            _DISC["disc"].close()
        _DISC["disc"] = importer.open_disc(path)
        _DISC["path"] = path
        _DISC["items"] = []
    return _DISC["disc"]


IMPORTABLE = (".CMP", ".MRG", ".MSD", ".CAT", ".CHRW", ".AUT", ".TEX")


def _asset_items(self, context):
    disc = get_disc(bpy.path.abspath(self.iso_path))
    if disc is None:
        return [("", "(set a valid disc image)", "")]
    if not _DISC["items"]:
        items = []
        for f in disc.list():
            if f.upper().endswith(IMPORTABLE):
                items.append((f, f, ""))
        _DISC["items"] = items or [("", "(no assets)", "")]
    return _DISC["items"]


_VARIANT_ITEMS: dict = {}  # Blender requires dynamic enum item lists to stay referenced


def _variant_items(self, context):
    disc = get_disc(bpy.path.abspath(getattr(self, "iso_path", "") or (prefs().iso_path if prefs() else "")))
    asset = getattr(self, "asset", "") or getattr(self, "filepath", "")
    key = (id(disc), asset)
    if key in _VARIANT_ITEMS:
        return _VARIANT_ITEMS[key]
    out = [("", "Default", "Textures shipped in the bundle")]
    if disc is not None:
        from .formats import assets
        for f in assets.color_variants_for(asset, disc.list()):
            out.append((f, f.split("/")[-1], ""))
    _VARIANT_ITEMS[key] = out
    return out


class _CommonOptions:
    lods: EnumProperty(name="LODs", items=[("HIGHEST", "Highest only", "Skip _m/_s level-of-detail models"),
                                           ("ALL", "All", "Import every LOD (lower LODs hidden)")],
                       default="HIGHEST")
    rig: EnumProperty(name="Hierarchy", items=[("AUTO", "Auto", "Armature for named/animated models"),
                                               ("ARMATURE", "Armature", "Always build an armature"),
                                               ("NONE", "Baked", "Bake node transforms into the mesh")],
                      default="AUTO")
    import_motions: BoolProperty(name="Motions", default=True,
                                 description="Import .mot clips as actions (one NLA track per clip)")
    shared_motions: BoolProperty(name="Shared skeletons/motions from disc", default=True,
                                 description="Also load MOT_*.MRG skeleton and motion sets from the disc image")
    scale: FloatProperty(name="Scale", default=1.0, min=0.0001, soft_max=10.0,
                         description="1 game unit is roughly 1 metre")
    texture_filter: EnumProperty(name="Texture filter", items=[("Linear", "Linear", ""), ("Closest", "Closest", "")],
                                 default="Linear")
    stage_blocks: IntProperty(name="Stage pattern blocks", default=1, min=1, max=5,
                              description="Odd number of pattern blocks per side to lay out (the game tiles 3x3)")
    merge_vertices: BoolProperty(name="Weld strip vertices", default=True)
    stage_pattern: IntProperty(name="Stage pattern", default=0, min=0, max=15,
                               description="Alternative ground layout stored in GRD_PatTbl (0 = first)")

    def make_options(self) -> build.Options:
        return build.Options(lods=self.lods, rig=self.rig, import_motions=self.import_motions,
                             shared_motions=self.shared_motions, scale=self.scale,
                             texture_filter=self.texture_filter, stage_blocks=self.stage_blocks,
                             merge_vertices=self.merge_vertices, stage_pattern=self.stage_pattern,
                             color_variant=getattr(self, "color_variant", "") or "")

    def draw_common(self, layout):
        layout.prop(self, "lods")
        layout.prop(self, "rig")
        layout.prop(self, "import_motions")
        layout.prop(self, "shared_motions")
        layout.prop(self, "scale")
        layout.prop(self, "texture_filter")
        layout.prop(self, "stage_blocks")
        layout.prop(self, "stage_pattern")
        layout.prop(self, "merge_vertices")


def _finish(op, ctx, t0):
    msg = f"Macross SDF: imported in {time.time() - t0:.1f}s"
    if ctx.report:
        msg += f" ({len(ctx.report)} warnings, see console)"
    op.report({"INFO"}, msg)


class IMPORT_SCENE_OT_macross_sdf_file(bpy.types.Operator, ImportHelper, _CommonOptions):
    """Import an extracted Macross SDF asset (.CMP/.MRG/.MSD or decompressed .bin)"""
    bl_idname = "import_scene.macross_sdf_file"
    bl_label = "Import Macross SDF Asset"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    filter_glob: StringProperty(default="*.cmp;*.mrg;*.msd;*.bin;*.cat;*.chrw;*.aut;*.tex", options={"HIDDEN"})
    color_variant: StringProperty(name="Colour variant (disc path)", default="",
                                  description="e.g. BIN.CVM/VF1J_COL_01.MRG (needs the disc image in preferences)")

    def draw(self, context):
        self.draw_common(self.layout)
        self.layout.prop(self, "color_variant")

    def execute(self, context):
        t0 = time.time()
        p = prefs()
        disc = get_disc(bpy.path.abspath(p.iso_path)) if p and p.iso_path else None
        with open(self.filepath, "rb") as fh:
            data = fh.read()
        name = os.path.basename(self.filepath)
        if name.lower().endswith(".bin") and "." in name[:-4]:
            name = name[:-4]
        _root, ctx = importer.import_bundle(data, name, self.make_options(), disc, self.filepath)
        _finish(self, ctx, t0)
        return {"FINISHED"}


class IMPORT_SCENE_OT_macross_sdf_disc(bpy.types.Operator, _CommonOptions):
    """Import a model, stage or motion archive directly from the Macross SDF disc image"""
    bl_idname = "import_scene.macross_sdf_disc"
    bl_label = "Import Macross SDF from Disc"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "asset"

    iso_path: StringProperty(name="Disc image", subtype="FILE_PATH", default="")
    asset: EnumProperty(name="Asset", items=_asset_items)
    color_variant: EnumProperty(name="Colour variant", items=_variant_items)

    def invoke(self, context, event):
        p = prefs()
        if not self.iso_path and p:
            self.iso_path = p.iso_path
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "iso_path")
        lay.prop(self, "asset")
        lay.prop(self, "color_variant")
        self.draw_common(lay)

    def execute(self, context):
        t0 = time.time()
        disc = get_disc(bpy.path.abspath(self.iso_path))
        if disc is None:
            self.report({"ERROR"}, "Disc image not found")
            return {"CANCELLED"}
        if not self.asset:
            self.report({"ERROR"}, "No asset selected")
            return {"CANCELLED"}
        p = prefs()
        if p and not p.iso_path:
            p.iso_path = self.iso_path
        data = disc.read(self.asset)
        _root, ctx = importer.import_bundle(data, self.asset.split("/")[-1], self.make_options(), disc, self.asset)
        _finish(self, ctx, t0)
        return {"FINISHED"}


def _motion_items(self, context):
    disc = get_disc(bpy.path.abspath(self.iso_path))
    if disc is None:
        return [("", "(set a valid disc image)", "")]
    items = [(f, f, "") for f in disc.list()
             if f.upper().split("/")[-1].startswith(("MOT_", "AUTH_")) or f.upper().endswith("_AC.CMP")]
    return items or [("", "(none)", "")]


_MOTION_ITEMS_CACHE = {}


def _motion_items_cached(self, context):
    key = self.iso_path
    if key not in _MOTION_ITEMS_CACHE:
        _MOTION_ITEMS_CACHE[key] = _motion_items(self, context)
    return _MOTION_ITEMS_CACHE[key]


class IMPORT_SCENE_OT_macross_sdf_motions(bpy.types.Operator):
    """Import motion clips (MOT_*.MRG, *_AC.CMP, AUTH_*.CMP) onto the active Macross SDF armature"""
    bl_idname = "import_scene.macross_sdf_motions"
    bl_label = "Import Macross SDF Motions onto Rig"
    bl_options = {"REGISTER", "UNDO"}

    iso_path: StringProperty(name="Disc image", subtype="FILE_PATH", default="")
    asset: EnumProperty(name="Motion archive", items=_motion_items_cached)
    filepath: StringProperty(name="...or extracted file", subtype="FILE_PATH", default="")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "ARMATURE"

    def invoke(self, context, event):
        p = prefs()
        if not self.iso_path and p:
            self.iso_path = p.iso_path
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        t0 = time.time()
        disc = get_disc(bpy.path.abspath(self.iso_path)) if self.iso_path else None
        if self.filepath:
            with open(bpy.path.abspath(self.filepath), "rb") as fh:
                data = fh.read()
            name = os.path.basename(self.filepath)
        elif disc is not None and self.asset:
            data = disc.read(self.asset)
            name = self.asset.split("/")[-1]
        else:
            self.report({"ERROR"}, "Choose a disc archive or an extracted file")
            return {"CANCELLED"}
        ctx, n = importer.apply_motions_to_rig(context.active_object, data, name, build.Options(), disc)
        self.report({"INFO"} if n else {"WARNING"}, f"Macross SDF: {n} clip(s) imported in {time.time() - t0:.1f}s"
                    + ("" if n else " - " + "; ".join(ctx.report[-2:])))
        return {"FINISHED"}


def menu_func(self, context):
    self.layout.operator(IMPORT_SCENE_OT_macross_sdf_file.bl_idname, text="Macross SDF Asset (.cmp/.mrg)")
    self.layout.operator(IMPORT_SCENE_OT_macross_sdf_disc.bl_idname, text="Macross SDF from Disc Image")
    self.layout.operator(IMPORT_SCENE_OT_macross_sdf_motions.bl_idname, text="Macross SDF Motions onto Rig")


CLASSES = (MACROSS_SDF_Preferences, IMPORT_SCENE_OT_macross_sdf_file, IMPORT_SCENE_OT_macross_sdf_disc,
           IMPORT_SCENE_OT_macross_sdf_motions)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    if _DISC["disc"] is not None:
        _DISC["disc"].close()
        _DISC.update(path=None, disc=None, items=[])
