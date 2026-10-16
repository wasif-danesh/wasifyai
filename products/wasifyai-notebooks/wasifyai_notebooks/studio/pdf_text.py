# SPDX-License-Identifier: Apache-2.0
"""Text for ReportLab's paragraph markup. v1 is English: Helvetica covers Latin-1, and a letter
outside it is replaced rather than drawn as a black box. (SurfSense picks DejaVu and CJK fonts
here; that needs matplotlib's font files and comes with the other languages.)"""

from xml.sax.saxutils import escape


def font_markup(text: str) -> str:
    """`text` escaped for markup, with characters Helvetica cannot draw replaced."""
    safe = "".join(ch if ord(ch) < 0x100 or ch.isspace() else "?" for ch in text)
    return escape(safe)
