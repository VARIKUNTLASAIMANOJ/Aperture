# Vendored fonts

`DejaVuSans.ttf` and `DejaVuSans-Bold.ttf`, used only when rendering a letter
to PDF (`core/india/pdf.py`).

**Why these are in the repository rather than resolved from the system:** the
built-in PDF fonts (Helvetica et al.) have no glyph for **₹ (U+20B9)**. Every
salary figure on an Indian offer letter rendered as a blank box. Picking a
system font instead would make the output depend on which machine generated
it — the same letter would look different, or break, in Docker or on Linux.

DejaVu is a Bitstream Vera derivative under a permissive licence that allows
redistribution. ~1.4 MB for a document a candidate receives and keeps.
