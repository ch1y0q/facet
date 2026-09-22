# Image fixtures

Real camera files, kept small. Regenerating or replacing one means rechecking the
NCLX values the tests assert on — that metadata is the point of the fixture, not
the picture.

## `canon_eos_r8_hdr_pq.hif` — 75 KiB, 600×400, 10-bit

An unmodified in-camera HDR PQ still from a Canon EOS R8.

| field | value |
|---|---|
| `Make` / `Model` | Canon / Canon EOS R8 |
| `color_primaries` | 9 — BT.2020 |
| `transfer_characteristics` | 16 — SMPTE ST 2084 (PQ) |
| `matrix_coefficients` | 1 — BT.709 |
| `full_range_flag` | 1 |

Note the matrix is **1, not 9**: an HDR PQ HEIF does not have to carry BT.2020
non-constant luminance, so nothing may gate on that field.

Decoded as plain 8-bit sRGB the frame reads mean 92.6/255 with p99 153 and no
pure-white pixel anywhere — the "dark and washed out" bug this fixture exists to
pin. It is also the regression guard for the tone curve's white point: a curve
normalised at diffuse white instead of the signal peak turns 21 648 of its
240 000 pixels pure white, inventing clipping in a frame that has none.

Source: <https://en.bandisoft.com/bandiview/help/hdr-samples/> ("Sample files for
HDR support"), retrieved 2026-09-22. Published by Bandisoft for testing HDR
support; no redistribution licence is stated on that page. Vendored here for
tests only.

## `sony_a7sm3_sdr.hif` — 108 KiB, 400×267

A Sony ILCE-7SM3 `.HIF`, downscaled from 4240×2832 and re-encoded at quality 40
with its original NCLX values preserved.

| field | value |
|---|---|
| `color_primaries` | 1 — BT.709 |
| `transfer_characteristics` | 13 — sRGB / sYCC |
| `matrix_coefficients` | 5 — BT.470BG |

`.HIF` is **not** a Canon-only extension and does **not** imply HDR: Sony's A7S III
and A7 IV write SDR stills under it. That is exactly why the loader gates on the
NCLX transfer rather than on the file extension, and this fixture is the case that
would break an extension-based gate.

Source: `tests/images/heif_other/cat.hif` in
<https://github.com/bigcat88/pillow_heif> (BSD-3-Clause), retrieved 2026-09-22.
