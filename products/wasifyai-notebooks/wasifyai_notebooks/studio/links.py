# SPDX-License-Identifier: Apache-2.0
# Adapted from SurfSense (Apache-2.0), worker/studio/office/markdown/links.py (the desktop
# app's backend), commit 622c1ded8. See ../../PROVENANCE.md.
"""Which link targets a built document may carry."""

_SCHEMES = ("http://", "https://", "mailto:")


def safe_href(href: str | None) -> str | None:
    """The target when it is a web or mail address; anything else stays plain text."""
    if href and href.strip().lower().startswith(_SCHEMES):
        return href.strip()
    return None
