# TIM2 textures and GS swizzling

Code: [`formats/tim2.py`](../../io_import_macross_sdf/formats/tim2.py),
[`formats/gs.py`](../../io_import_macross_sdf/formats/gs.py).

Confidence: **confirmed**.

- All 2,997 TIM2 files on the disc decode.
- Swizzled pixels were verified visually on square and non-square 4- and 8-bit images (e.g. 512×128, 128×256, 1024×512).
- The GS address tables reproduce a known-good unswizzle bit-for-bit on square 8-bit textures.

## File layout

The layout is standard TIM2, with one game-specific flag:

| file offset | meaning |
|---|---|
| 0x00 | `TIM2` |
| 0x04 | version (4) |
| 0x05 | alignment: 0 → pictures at 0x10, 1 → at 0x80 |
| 0x06 | u16 picture count |
| 0x08 | u16 id (matches the model texture-table id) |
| **0x0A** | **0xFF = pixel data is GS-swizzled; 0x00 = linear** |

Picture header: `u32 total, u32 clut_size, u32 image_size, u16 header_size,
u16 clut_colours, u8 format, u8 mipmaps, u8 clut_type, u8 image_type, u16 w,
u16 h, u64 TEX0, u64 TEX1, u32 regs, u32 TEXCLUT`. The image data starts at
`picture + header_size`, and the CLUT follows the image.

Observed on this disc:

- **Image types:** 4 (4-bit indexed) and 5 (8-bit indexed).
- **CLUT types:** 3 (32-bit RGBA, CSM1) and once 1 (16-bit).
- **Mipmaps:** up to 7 levels. The importer uses level 0.
- **Extended header:** `eXt\0` appears at picture+0x30 in 128-byte headers.

Only tiny textures (≤ 16×16 and 8×32) are linear. All others carry the
0xFF flag.

## Palette

8-bit CSM1 CLUTs use the standard PS2 permutation: entries 8–15 and 16–23
are swapped within every 32-entry block. Alpha 0x80 = opaque, so it is
expanded as `min(a * 255 / 128, 255)`.

## Swizzle

The image bytes are the raster dump of a **PSMCT32** rectangle that was
uploaded to GS memory and then sampled as PSMT8 or PSMT4. The rectangle is:

- PSMT8: `(w/2) × (h/2)` PSMCT32 pixels, buffer width `max(1, (w/2)/64)`
- PSMT4: `(w/2) × (h/4)` PSMCT32 pixels, same rule for the buffer width

To unswizzle, write the bytes into a virtual GS memory with the PSMCT32
page/block/column tables, then read texel addresses with the PSMT8 or PSMT4
tables, using TBW = `max(2, w/64)`. `gs.py` contains the block and column
tables for PSMCT32, PSMT8 and PSMT4.

The common "unswizzle8/unswizzle4" one-liners found online are correct only
for square power-of-two images. Non-square 4-bit textures need the
memory-model approach.

## Blender import

Decoded RGBA is flipped to bottom-up and written with
`Image.pixels.foreach_set()` (float32 numpy). The image is then packed into
the .blend, so no temporary files are involved. Each image carries diagnostic
properties: `tim2_tex0`, `tim2_swizzled`, `has_alpha`, `has_partial_alpha`.

## Colour variants

`VF1*_COL_00…05.MRG` are tex-only archives with alternative liveries; they
use the same texture names as the craft bundle. In the importer, choose
**Colour variant**, or pass `--variant` to the test tool.
