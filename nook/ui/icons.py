"""Vector icon set for Nook.

Draws crisp, theme-coloured icons with QPainter instead of relying on emoji
glyphs or bundled image assets. Every icon is authored on a 24x24 grid with a
stroke-based (Feather/Lucide-like) look and is rendered on demand.

Usage::

    from nook.ui.icons import icons

    button.setIcon(icons.icon("play"))
    label.setPixmap(icons.pixmap("library", size=48))
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

VIEWBOX = 24.0
STROKE = 2.0

# Colour used for icons when the caller does not override it. Updated by the
# active theme so that stroke icons stay legible on both dark and light modes.
_DEFAULT_COLOR = "#E9E9E9"

_cache: Dict[Tuple[str, str, int], QIcon] = {}
_scale_factor = 2.0  # supersample factor for crisp HiDPI rendering


# ---------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------
def set_color(color: str) -> None:
    """Set the default stroke colour (clears the icon cache when it changes)."""
    global _DEFAULT_COLOR
    if color and color != _DEFAULT_COLOR:
        _DEFAULT_COLOR = color
        _cache.clear()


def get_color() -> str:
    return _DEFAULT_COLOR


# ---------------------------------------------------------------------------
# Low level painting helpers (all coordinates live in the 24x24 viewbox)
# ---------------------------------------------------------------------------
def _pen(painter: QPainter, color: str, width: float = STROKE) -> None:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _line(painter: QPainter, pts: Sequence[Tuple[float, float]], color: str, width: float = STROKE) -> None:
    _pen(painter, color, width)
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    painter.drawPath(path)


def _poly(painter: QPainter, pts: Sequence[Tuple[float, float]], color: str) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))


def _circle(painter: QPainter, cx: float, cy: float, r: float, color: str,
            fill: bool = False, width: float = STROKE) -> None:
    if fill:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
    else:
        _pen(painter, color, width)
    painter.drawEllipse(QPointF(cx, cy), r, r)


def _rrect(painter: QPainter, x: float, y: float, w: float, h: float, r: float,
           color: str, fill: bool = True, width: float = STROKE) -> None:
    rect = QRectF(x, y, w, h)
    if fill:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
    else:
        _pen(painter, color, width)
    painter.drawRoundedRect(rect, r, r)


def _path(painter: QPainter, builder: Callable[[QPainterPath], None], color: str,
          fill: bool = False, width: float = STROKE) -> None:
    path = QPainterPath()
    builder(path)
    if fill:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
    else:
        _pen(painter, color, width)
    painter.drawPath(path)


def _star(painter: QPainter, cx: float, cy: float, r: float, points: int,
          inner_ratio: float, color: str) -> None:
    pts: List[Tuple[float, float]] = []
    for i in range(points * 2):
        radius = r if i % 2 == 0 else r * inner_ratio
        angle = -math.pi / 2 + i * math.pi / points
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    _poly(painter, pts, color)


def _heart_path(path: QPainterPath) -> None:
    path.moveTo(12.0, 20.2)
    path.cubicTo(3.4, 14.4, 1.9, 10.2, 4.5, 7.2)
    path.cubicTo(7.0, 4.3, 10.7, 5.3, 12.0, 7.7)
    path.cubicTo(13.3, 5.3, 17.0, 4.3, 19.5, 7.2)
    path.cubicTo(22.1, 10.2, 20.6, 14.4, 12.0, 20.2)
    path.closeSubpath()


# ---------------------------------------------------------------------------
# Icon drawings
# ---------------------------------------------------------------------------
def _play(p: QPainter, c: str) -> None:
    _poly(p, [(7.5, 4.8), (20.0, 12.0), (7.5, 19.2)], c)


def _pause(p: QPainter, c: str) -> None:
    _rrect(p, 6.5, 5.0, 3.8, 14.0, 1.6, c)
    _rrect(p, 13.7, 5.0, 3.8, 14.0, 1.6, c)


def _check(p: QPainter, c: str) -> None:
    _line(p, [(4.8, 12.6), (9.6, 17.4), (19.4, 6.8)], c, 2.2)


def _close(p: QPainter, c: str) -> None:
    _line(p, [(6.2, 6.2), (17.8, 17.8)], c, 2.1)
    _line(p, [(17.8, 6.2), (6.2, 17.8)], c, 2.1)


def _plus(p: QPainter, c: str) -> None:
    _line(p, [(12.0, 5.2), (12.0, 18.8)], c, 2.1)
    _line(p, [(5.2, 12.0), (18.8, 12.0)], c, 2.1)


def _refresh(p: QPainter, c: str) -> None:
    # Circular arrow with a gap at the top-right
    _pen(p, c, 2.1)
    p.drawArc(QRectF(4.4, 4.4, 15.2, 15.2), 55 * 16, 260 * 16)
    # Arrow head sitting on the arc start
    _poly(p, [(16.9, 3.4), (18.9, 8.4), (13.6, 7.4)], c)


def _more(p: QPainter, c: str) -> None:
    for x in (5.6, 12.0, 18.4):
        _circle(p, x, 12.0, 1.7, c, fill=True)


def _clock(p: QPainter, c: str) -> None:
    _circle(p, 12.0, 12.0, 8.4, c)
    _line(p, [(12.0, 6.9), (12.0, 12.0), (15.9, 14.2)], c, 1.9)


def _folder(p: QPainter, c: str) -> None:
    def build(path: QPainterPath) -> None:
        path.moveTo(3.2, 18.8)
        path.lineTo(3.2, 7.2)
        path.quadTo(3.2, 5.6, 4.8, 5.6)
        path.lineTo(8.9, 5.6)
        path.lineTo(11.0, 7.9)
        path.lineTo(19.2, 7.9)
        path.quadTo(20.8, 7.9, 20.8, 9.5)
        path.lineTo(20.8, 17.2)
        path.quadTo(20.8, 18.8, 19.2, 18.8)
        path.closeSubpath()
    _path(p, build, c)


def _folder_open(p: QPainter, c: str) -> None:
    def build(path: QPainterPath) -> None:
        path.moveTo(3.2, 18.8)
        path.lineTo(3.2, 7.2)
        path.quadTo(3.2, 5.6, 4.8, 5.6)
        path.lineTo(8.9, 5.6)
        path.lineTo(11.0, 7.9)
        path.lineTo(19.2, 7.9)
        path.quadTo(20.8, 7.9, 20.8, 9.5)
        path.lineTo(20.8, 10.9)
    _path(p, build, c)

    def flap(path: QPainterPath) -> None:
        path.moveTo(3.2, 18.8)
        path.lineTo(5.6, 11.6)
        path.quadTo(5.9, 10.9, 6.7, 10.9)
        path.lineTo(21.4, 10.9)
        path.quadTo(22.1, 10.9, 21.9, 11.6)
        path.lineTo(19.5, 18.2)
        path.quadTo(19.2, 18.8, 18.5, 18.8)
        path.closeSubpath()
    _path(p, flap, c)


def _gear(p: QPainter, c: str) -> None:
    teeth = 8
    outer, inner = 9.4, 6.9
    pts: List[Tuple[float, float]] = []
    for i in range(teeth):
        a = i * (360.0 / teeth)
        for delta, radius in ((-16.0, inner), (-9.0, outer), (9.0, outer), (16.0, inner)):
            ang = math.radians(a + delta)
            pts.append((12 + radius * math.cos(ang), 12 + radius * math.sin(ang)))
    _poly_outline = QPainterPath()
    _poly_outline.moveTo(QPointF(*pts[0]))
    for pt in pts[1:]:
        _poly_outline.lineTo(QPointF(*pt))
    _poly_outline.closeSubpath()
    _pen(p, c, 1.8)
    p.drawPath(_poly_outline)
    _circle(p, 12.0, 12.0, 2.9, c, width=1.8)


def _globe(p: QPainter, c: str) -> None:
    _circle(p, 12.0, 12.0, 8.6, c)
    p.save()
    _pen(p, c, 1.8)
    p.drawEllipse(QPointF(12.0, 12.0), 3.9, 8.6)
    p.drawLine(QPointF(3.6, 12.0), QPointF(20.4, 12.0))
    p.restore()


def _eye(p: QPainter, c: str) -> None:
    def build(path: QPainterPath) -> None:
        path.moveTo(2.0, 12.0)
        path.cubicTo(5.0, 6.4, 8.5, 4.4, 12.0, 4.4)
        path.cubicTo(15.5, 4.4, 19.0, 6.4, 22.0, 12.0)
        path.cubicTo(19.0, 17.6, 15.5, 19.6, 12.0, 19.6)
        path.cubicTo(8.5, 19.6, 5.0, 17.6, 2.0, 12.0)
        path.closeSubpath()
    _path(p, build, c)
    _circle(p, 12.0, 12.0, 3.1, c, width=1.9)


def _eye_off(p: QPainter, c: str) -> None:
    _eye(p, c)
    _line(p, [(4.2, 4.2), (19.8, 19.8)], c, 2.1)


def _heart(p: QPainter, c: str) -> None:
    _path(p, _heart_path, c, fill=True)


def _heart_outline(p: QPainter, c: str) -> None:
    _path(p, _heart_path, c, fill=False, width=1.9)


def _heart_broken(p: QPainter, c: str) -> None:
    # Filled heart with a lightning-shaped gap splitting it in two
    heart = QPainterPath()
    _heart_path(heart)
    p.save()
    p.fillPath(heart, QColor(c))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    pen = QPen(QColor(0, 0, 0))
    pen.setWidthF(3.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    zig = QPainterPath(QPointF(13.6, 3.6))
    for pt in ((10.6, 9.2), (14.4, 11.6), (10.4, 15.4), (13.2, 21.0)):
        zig.lineTo(QPointF(*pt))
    p.drawPath(zig)
    p.restore()


def _library(p: QPainter, c: str) -> None:
    # A small shelf of books: two upright and one leaning
    _rrect(p, 4.4, 5.6, 3.4, 12.8, 0.9, c)
    _rrect(p, 9.2, 3.8, 3.4, 14.6, 0.9, c)
    p.save()
    p.translate(16.1, 11.1)
    p.rotate(13)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c))
    p.drawRoundedRect(QRectF(-1.7, -7.3, 3.4, 14.6), 0.9, 0.9)
    p.restore()
    _line(p, [(2.8, 19.4), (21.2, 19.4)], c, 1.9)


def _grid(p: QPainter, c: str) -> None:
    _rrect(p, 3.6, 3.6, 7.1, 7.1, 2.1, c, fill=False, width=1.9)
    _rrect(p, 13.3, 3.6, 7.1, 7.1, 2.1, c, fill=False, width=1.9)
    _rrect(p, 3.6, 13.3, 7.1, 7.1, 2.1, c, fill=False, width=1.9)
    _rrect(p, 13.3, 13.3, 7.1, 7.1, 2.1, c, fill=False, width=1.9)


def _search(p: QPainter, c: str) -> None:
    _circle(p, 10.6, 10.6, 6.6, c, width=2.0)
    _line(p, [(15.4, 15.4), (20.4, 20.4)], c, 2.2)


def _sun(p: QPainter, c: str) -> None:
    _circle(p, 12.0, 12.0, 4.2, c, width=1.9)
    for i in range(8):
        ang = math.radians(i * 45)
        x1, y1 = 12 + 6.6 * math.cos(ang), 12 + 6.6 * math.sin(ang)
        x2, y2 = 12 + 9.2 * math.cos(ang), 12 + 9.2 * math.sin(ang)
        _line(p, [(x1, y1), (x2, y2)], c, 1.9)


def _moon(p: QPainter, c: str) -> None:
    p.save()
    painter_path = QPainterPath()
    painter_path.addEllipse(QPointF(11.4, 12.0), 8.4, 8.4)
    p.fillPath(painter_path, QColor(c))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    cut = QPainterPath()
    cut.addEllipse(QPointF(16.4, 9.2), 7.4, 7.4)
    p.fillPath(cut, QColor(0, 0, 0))
    p.restore()


def _image(p: QPainter, c: str) -> None:
    _rrect(p, 3.2, 4.4, 17.6, 15.2, 3.0, c, fill=False, width=1.9)
    _circle(p, 8.6, 9.6, 1.9, c, fill=True)
    _line(p, [(4.6, 17.6), (9.6, 12.4), (13.0, 15.6), (15.4, 13.2), (19.4, 17.2)], c, 1.9)


def _sparkles(p: QPainter, c: str) -> None:
    _star(p, 10.4, 13.4, 8.4, 4, 0.30, c)
    _star(p, 18.4, 6.4, 4.2, 4, 0.30, c)


def _download(p: QPainter, c: str) -> None:
    _line(p, [(12.0, 3.6), (12.0, 14.6)], c, 2.0)
    _poly(p, [(8.2, 11.0), (12.0, 14.9), (15.8, 11.0)], c)
    _line(p, [(4.6, 15.4), (4.6, 18.6), (19.4, 18.6), (19.4, 15.4)], c, 1.9)


def _film(p: QPainter, c: str) -> None:
    _rrect(p, 3.0, 4.6, 18.0, 14.8, 2.6, c, fill=False, width=1.9)
    p.save()
    _pen(p, c, 1.7)
    p.drawLine(QPointF(8.2, 4.8), QPointF(8.2, 19.2))
    p.drawLine(QPointF(15.8, 4.8), QPointF(15.8, 19.2))
    p.restore()
    for y in (6.6, 11.6, 16.6):
        _rrect(p, 4.6, y - 1.0, 2.2, 2.0, 0.6, c)
        _rrect(p, 17.2, y - 1.0, 2.2, 2.0, 0.6, c)


def _coffee(p: QPainter, c: str) -> None:
    def cup(path: QPainterPath) -> None:
        path.moveTo(5.6, 8.4)
        path.lineTo(6.3, 16.6)
        path.quadTo(6.5, 18.7, 8.6, 18.7)
        path.lineTo(13.2, 18.7)
        path.quadTo(15.3, 18.7, 15.5, 16.6)
        path.lineTo(16.2, 8.4)
    _path(p, cup, c, fill=False, width=1.9)

    # Handle
    p.save()
    _pen(p, c, 1.9)
    p.drawArc(QRectF(14.1, 10.4, 6.0, 4.8), -75 * 16, 150 * 16)
    p.restore()

    # Steam
    _line(p, [(9.0, 3.4), (9.0, 6.2)], c, 1.6)
    _line(p, [(12.4, 3.4), (12.4, 6.2)], c, 1.6)


def _list(p: QPainter, c: str) -> None:
    for y in (6.8, 12.0, 17.2):
        _circle(p, 4.3, y, 1.35, c, fill=True)
        _line(p, [(8.4, y), (20.0, y)], c, 1.9)


def _palette(p: QPainter, c: str) -> None:
    def build(path: QPainterPath) -> None:
        path.moveTo(12.0, 3.4)
        path.cubicTo(6.4, 3.4, 2.4, 7.2, 2.4, 12.0)
        path.cubicTo(2.4, 16.9, 6.6, 20.6, 12.0, 20.6)
        path.cubicTo(13.8, 20.6, 14.6, 19.5, 14.6, 18.4)
        path.cubicTo(14.6, 17.4, 13.8, 16.6, 13.8, 15.7)
        path.cubicTo(13.8, 14.6, 14.7, 13.8, 15.9, 13.8)
        path.lineTo(18.1, 13.8)
        path.cubicTo(20.6, 13.8, 21.6, 11.9, 21.6, 9.9)
        path.cubicTo(21.6, 6.1, 17.2, 3.4, 12.0, 3.4)
        path.closeSubpath()
    _path(p, build, c, fill=False, width=1.8)
    for cx, cy in ((8.0, 9.0), (12.6, 7.4), (16.4, 9.6), (7.2, 14.2)):
        _circle(p, cx, cy, 1.35, c, fill=True)


def _arrow_left(p: QPainter, c: str) -> None:
    _line(p, [(19.2, 12.0), (5.2, 12.0)], c, 2.1)
    _poly(p, [(11.0, 5.8), (4.6, 12.0), (11.0, 18.2)], c)


def _chevron_down(p: QPainter, c: str) -> None:
    _line(p, [(5.8, 9.2), (12.0, 15.4), (18.2, 9.2)], c, 2.1)


def _chevron_up(p: QPainter, c: str) -> None:
    _line(p, [(5.8, 14.8), (12.0, 8.6), (18.2, 14.8)], c, 2.1)


def _chevron_right(p: QPainter, c: str) -> None:
    _line(p, [(9.2, 5.8), (15.4, 12.0), (9.2, 18.2)], c, 2.1)


def _chevron_left(p: QPainter, c: str) -> None:
    _line(p, [(14.8, 5.8), (8.6, 12.0), (14.8, 18.2)], c, 2.1)


def _circle_icon(p: QPainter, c: str) -> None:
    _circle(p, 12.0, 12.0, 8.0, c, width=1.9)


def _tv(p: QPainter, c: str) -> None:
    # A cosy little television set with a play glyph on the screen.
    _rrect(p, 3.0, 6.0, 18.0, 12.4, 2.6, c, fill=False, width=1.9)
    _line(p, [(12.0, 18.4), (12.0, 21.2)], c, 1.9)
    _line(p, [(8.6, 21.4), (15.4, 21.4)], c, 1.9)
    _poly(p, [(10.6, 9.2), (15.6, 12.2), (10.6, 15.2)], c)


def _external_link(p: QPainter, c: str) -> None:
    # Box with an arrow escaping to the top right.
    _rrect(p, 4.0, 9.6, 10.4, 10.4, 2.4, c, fill=False, width=1.8)
    _line(p, [(11.0, 13.0), (19.4, 4.6)], c, 1.9)
    _poly(p, [(14.2, 4.2), (20.2, 4.2), (20.2, 10.2)], c)


def _trash(p: QPainter, c: str) -> None:
    _line(p, [(4.2, 7.2), (19.8, 7.2)], c, 1.9)
    _rrect(p, 9.4, 4.2, 5.2, 2.2, 0.9, c, fill=False, width=1.7)

    def body(path: QPainterPath) -> None:
        path.moveTo(6.4, 7.8)
        path.lineTo(7.0, 19.0)
        path.quadTo(7.1, 20.4, 8.4, 20.4)
        path.lineTo(15.6, 20.4)
        path.quadTo(16.9, 20.4, 17.0, 19.0)
        path.lineTo(17.6, 7.8)
    _path(p, body, c, fill=False, width=1.8)
    _line(p, [(10.3, 10.6), (10.3, 17.4)], c, 1.6)
    _line(p, [(13.7, 10.6), (13.7, 17.4)], c, 1.6)


def _pencil(p: QPainter, c: str) -> None:
    # A pencil tilted at 45 degrees with a triangular tip.
    def body(path: QPainterPath) -> None:
        path.moveTo(15.9, 5.1)
        path.lineTo(18.9, 8.1)
        path.lineTo(8.5, 18.5)
        path.lineTo(5.5, 15.5)
        path.closeSubpath()
    _path(p, body, c, fill=False, width=1.8)

    def tip(path: QPainterPath) -> None:
        path.moveTo(5.5, 15.5)
        path.lineTo(3.6, 20.4)
        path.lineTo(8.5, 18.5)
    _path(p, tip, c, fill=False, width=1.8)

    _line(p, [(14.0, 7.0), (17.0, 10.0)], c, 1.6)


ICONS: Dict[str, Callable[[QPainter, str], None]] = {
    "play": _play,
    "pause": _pause,
    "check": _check,
    "close": _close,
    "plus": _plus,
    "refresh": _refresh,
    "more": _more,
    "clock": _clock,
    "folder": _folder,
    "folder-open": _folder_open,
    "gear": _gear,
    "globe": _globe,
    "eye": _eye,
    "eye-off": _eye_off,
    "heart": _heart,
    "heart-outline": _heart_outline,
    "heart-broken": _heart_broken,
    "list": _list,
    "grid": _grid,
    "search": _search,
    "sun": _sun,
    "moon": _moon,
    "image": _image,
    "sparkles": _sparkles,
    "download": _download,
    "film": _film,
    "coffee": _coffee,
    "library": _library,
    "palette": _palette,
    "arrow-left": _arrow_left,
    "chevron-down": _chevron_down,
    "chevron-up": _chevron_up,
    "chevron-right": _chevron_right,
    "chevron-left": _chevron_left,
    "circle": _circle_icon,
    "tv": _tv,
    "external-link": _external_link,
    "trash": _trash,
    "pencil": _pencil,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def pixmap(name: str, size: int = 20, color: Optional[str] = None) -> QPixmap:
    """Render a single icon into a QPixmap of ``size`` logical pixels."""
    color = color or _DEFAULT_COLOR
    draw = ICONS.get(name)
    physical = max(1, int(round(size * _scale_factor)))
    pm = QPixmap(physical, physical)
    pm.fill(Qt.GlobalColor.transparent)
    if draw is None:
        pm.setDevicePixelRatio(_scale_factor)
        return pm

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.scale(physical / VIEWBOX, physical / VIEWBOX)
    draw(painter, color)
    painter.end()
    pm.setDevicePixelRatio(_scale_factor)
    return pm


def icon(name: str, size: int = 20, color: Optional[str] = None) -> QIcon:
    """Return a cached QIcon for ``name``."""
    color = color or _DEFAULT_COLOR
    key = (name, color, size)
    cached = _cache.get(key)
    if cached is None:
        cached = QIcon(pixmap(name, size=size, color=color))
        _cache[key] = cached
    return cached


def available() -> Sequence[str]:
    return sorted(ICONS.keys())
