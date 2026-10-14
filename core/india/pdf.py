"""
Rendering a generated letter to PDF.

WHY xhtml2pdf AND NOT WeasyPrint
--------------------------------
WeasyPrint is the better renderer and was the first choice. It needs pango,
cairo and their GObject stack as *system* libraries; on this machine those
exist via Homebrew but the application runs under miniconda, which ships its
own conflicting glib — WeasyPrint imports and then dies inside GObject. That
is an environment fight that would have to be re-won on every machine the
project is cloned to, for a feature whose whole job is "produce a file".

xhtml2pdf is pure Python on top of reportlab: no system libraries, installs
anywhere pip runs. The cost is a smaller CSS subset — no flexbox, no grid —
which is why the letter templates use tables for their two-column blocks.
That is not a concession so much as the correct construct for a paginated
document: a table breaks across pages predictably and a flex row does not.

If a crisper result is ever needed, swapping in WeasyPrint or a headless
browser means replacing `html_to_pdf` and nothing else — the templates are
already print-shaped.
"""

from __future__ import annotations

import io
import logging
import os
import re
from functools import lru_cache

log = logging.getLogger(__name__)

#: Vendored, not resolved from the system. The built-in PDF fonts have no
#: glyph for ₹ (U+20B9), so every salary figure printed as a blank box; and a
#: system font would make the same letter render differently depending on
#: which machine produced it. See assets/fonts/README.md.
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "fonts",
)
_FONT_FAMILY = "DejaVuSans"


class PdfError(RuntimeError):
    """Raised when a letter could not be rendered. Never swallowed."""


#: Properties the renderer does not implement. Stripped before rendering so
#: its warning stream stays quiet enough that a REAL problem is visible in it.
_UNSUPPORTED = re.compile(
    r"\s*(border-collapse|box-shadow|border-radius|letter-spacing|"
    r"font-variant-numeric|text-transform)\s*:[^;}]*;?",
    re.I,
)


def _strip_unsupported(html: str) -> str:
    """
    Remove declarations xhtml2pdf cannot apply.

    It ignores them anyway; removing them first means its log carries only
    things worth reading. text-transform is the one with a visible effect —
    uppercase section headings render in their source case — so the templates
    write those headings already capitalised.
    """
    return _UNSUPPORTED.sub("", html)


@lru_cache(maxsize=1)
def _font_css() -> str:
    """
    The @font-face block that gives the document a rupee glyph, or "" if the
    vendored files are absent.

    @font-face with an absolute path, NOT reportlab's registerFont: xhtml2pdf
    resolves fonts from the stylesheet it parses and never consults reportlab's
    registry, so a registered family is reported as "not known to this
    document" and silently replaced by Helvetica — which is how the rupee boxes
    came back after the fonts were apparently installed.

    Missing files degrade to a warning and a Helvetica letter rather than
    refusing to issue one.
    """
    regular = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
    bold = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
    if not (os.path.exists(regular) and os.path.exists(bold)):
        log.warning(
            "assets/fonts is missing DejaVu — ₹ will not render in PDFs. "
            "Expected at %s", _FONT_DIR,
        )
        return ""

    return (
        "<style>"
        f"@font-face {{ font-family: '{_FONT_FAMILY}'; src: url('{regular}'); }}"
        f"@font-face {{ font-family: '{_FONT_FAMILY}'; src: url('{bold}'); "
        "font-weight: bold; }"
        "body, td, th, div, p, h1, h2, h3, li, strong, small, span, b "
        f"{{ font-family: '{_FONT_FAMILY}'; }}"
        "</style>"
    )


def html_to_pdf(html: str) -> bytes:
    """
    Render a complete HTML document to PDF bytes.

    Raises PdfError rather than returning a broken file: a zero-byte or
    truncated PDF attached to an offer letter is worse than an error an
    operator can see.
    """
    if not html or not html.strip():
        raise PdfError("There is no document body to render.")

    try:
        from xhtml2pdf import pisa
    except ImportError as exc:                         # pragma: no cover
        raise PdfError(
            "PDF rendering needs xhtml2pdf — run `pip install -r requirements.txt`."
        ) from exc

    # APPENDED, not prepended. The templates set their own font-family on
    # body; prepending put this first and let that rule win, so the document
    # still rendered in Helvetica and still lost the rupee sign.
    body = _strip_unsupported(html) + _font_css()

    buffer = io.BytesIO()
    # BYTES, not a str: passing unicode together with encoding= makes html5lib
    # raise, and passing unicode without it leaves ₹ and other non-ASCII to
    # chance. Encoding here settles both.
    status = pisa.CreatePDF(
        io.BytesIO(body.encode("utf-8")),
        dest=buffer,
        encoding="utf-8",
    )

    if status.err:
        raise PdfError(f"The document could not be rendered to PDF ({status.err} error(s)).")

    data = buffer.getvalue()
    if not data.startswith(b"%PDF-"):
        raise PdfError("The renderer produced something that is not a PDF.")
    return data


def pdf_filename(document_number: str | None, fallback: str) -> str:
    """
    A filename a person can find later.

    Document numbers carry slashes (OFR/2026/CAND-1), which are path
    separators — left in, the browser saves 'CAND-1' and the rest is lost.
    """
    base = (document_number or fallback).strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-") or fallback
    return f"{safe}.pdf"
