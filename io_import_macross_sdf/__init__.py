"""Macross SDF (PS2, SLPM-65405) importer for Blender 5.2.

File > Import > Macross SDF ...
  * Asset file  - an extracted .CMP / .MRG / .MSD / decompressed .bin file
  * Disc image  - pick any model/stage/motion archive straight from the ISO

The ``formats`` sub-package has no Blender dependency and can be used from a
plain Python interpreter (see tools/).
"""

try:
    import bpy  # noqa: F401
except ImportError:  # used as a plain library outside Blender
    bpy = None

if bpy is not None:
    from ._addon import get_disc, register, unregister  # noqa: F401
