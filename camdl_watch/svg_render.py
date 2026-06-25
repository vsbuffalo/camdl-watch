"""Render a matplotlib figure to an inline, responsive SVG string.

Why SVG: a phone scales a fixed-pixel PNG to fit width and the result is
illegible — you can't pan/zoom into a single panel of a dense pair plot. An
inline SVG scales crisply, so the browser's native pinch-zoom keeps axis
labels, ticks, and structure sharp at any magnification.

Why *partial* rasterization: a pure-vector SVG of a scatter cloud is enormous
(a 9x9 pair plot ran ~35 MB — every point becomes a path node). We rasterize
only the dense data artists (point clouds, long trace lines) and leave the
text/axes/labels vector. That collapses the file to a few MB while preserving
exactly the part a reader zooms in to *read* (the labels), which stays crisp.
"""

from __future__ import annotations

import io
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# Resolution of the rasterized (point-cloud / trace-line) layers. 150 dpi keeps
# the pair plot ~3 MB while the vector text stays sharp regardless of dpi.
DEFAULT_DPI = 150


def rasterize_dense(fig: Figure, min_pts: int = 50) -> int:
    """Mark dense data artists for rasterization, in place. Returns the count.

    Rasterizes every ``PathCollection`` (``ax.scatter``) and any ``Line2D``
    with more than ``min_pts`` vertices (scatter-via-``plot`` and long trace
    lines). Text, spines, ticks, thin prior overlays, and short hist outlines
    stay vector.
    """
    n = 0
    for ax in fig.axes:
        for coll in ax.collections:
            coll.set_rasterized(True)
            n += 1
        for line in ax.lines:
            if len(line.get_xdata()) > min_pts:
                line.set_rasterized(True)
                n += 1
    return n


def _make_responsive(svg: str) -> str:
    """Strip the XML/doctype prolog and rewrite the root ``<svg>`` tag to scale
    to its container width while preserving aspect ratio via the ``viewBox``."""
    start = svg.find("<svg")
    if start > 0:
        svg = svg[start:]
    end = svg.find(">")
    if end == -1:
        return svg
    tag, rest = svg[: end + 1], svg[end + 1 :]
    tag = re.sub(r'\s(?:width|height)="[^"]*"', "", tag)
    tag = tag.replace(
        "<svg",
        '<svg width="100%" height="auto" preserveAspectRatio="xMidYMid meet"',
        1,
    )
    return tag + rest


def fig_to_svg(fig: Figure, *, dpi: int = DEFAULT_DPI, min_pts: int = 50) -> str:
    """Rasterize dense artists, serialize ``fig`` to a responsive inline SVG
    string, and close the figure (we own it; nothing else will)."""
    rasterize_dense(fig, min_pts=min_pts)
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    return _make_responsive(buf.getvalue())


# Resolution for the downloadable PNG. Higher than the inline-SVG raster layers
# (this is the full-quality "clean" copy the download link points at).
PNG_DPI = 200


def fig_to_png(fig: Figure, *, dpi: int = PNG_DPI) -> bytes:
    """Serialize ``fig`` to a clean full-quality PNG and close it. No selective
    rasterization — savefig rasterizes the whole figure at ``dpi`` anyway, so
    this is just the plain high-resolution copy."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()
