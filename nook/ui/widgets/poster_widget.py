"""Poster image widget with rounded corners and warm placeholder fallback."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget


class PosterWidget(QWidget):
    """Draws a rounded cover poster image or an aesthetic cozy placeholder."""

    # Warm cozy gradient color pairs for fallback posters
    GRADIENT_PAIRS = [
        ("#8A5038", "#4A281E"),  # Warm Terracotta
        ("#3E5641", "#1E2B20"),  # Deep Sage
        ("#91632C", "#4F3312"),  # Warm Amber
        ("#644558", "#33212C"),  # Muted Plum
        ("#3B5366", "#1B2833"),  # Dusty Slate
        ("#7B4F35", "#3E2517"),  # Roasted Cinnamon
    ]

    def __init__(
        self,
        image_path: Optional[str] = None,
        title: str = "",
        corner_radius: int = 12,
        fixed_size: Optional[QSize] = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.image_path = image_path
        self.title = title
        self.corner_radius = corner_radius
        self._cached_pixmap: Optional[QPixmap] = None

        if fixed_size:
            self.setFixedSize(fixed_size)
        else:
            self.setMinimumSize(120, 180)

        self._load_pixmap()

    def set_image(self, image_path: Optional[str], title: Optional[str] = None) -> None:
        self.image_path = image_path
        if title is not None:
            self.title = title
        self._load_pixmap()
        self.update()

    def _load_pixmap(self) -> None:
        self._cached_pixmap = None
        if self.image_path:
            p = Path(self.image_path)
            if p.exists() and p.is_file():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    self._cached_pixmap = pix

    def _get_gradient_colors(self) -> tuple[str, str]:
        # Hash title to deterministically choose a color pair
        hash_val = int(hashlib.md5(self.title.encode("utf-8")).hexdigest(), 16)
        return self.GRADIENT_PAIRS[hash_val % len(self.GRADIENT_PAIRS)]

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), float(self.corner_radius), float(self.corner_radius))
        painter.setClipPath(path)

        if self._cached_pixmap and not self._cached_pixmap.isNull():
            # Scale pixmap smoothly to fill widget keeping aspect ratio by cropping centered
            scaled = self._cached_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # Center cropped
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            # Draw cozy gradient placeholder
            c1_str, c2_str = self._get_gradient_colors()
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, QColor(c1_str))
            grad.setColorAt(1.0, QColor(c2_str))
            painter.fillPath(path, QBrush(grad))

            # Draw subtle decorative inner border
            painter.setPen(QColor(255, 255, 255, 30))
            painter.drawRoundedRect(
                QRectF(rect).adjusted(1.0, 1.0, -1.0, -1.0),
                float(self.corner_radius - 1),
                float(self.corner_radius - 1)
            )

            # Draw film / video cozy icon symbol
            painter.setPen(QColor(255, 255, 255, 120))
            icon_font = QFont(self.font())
            icon_font.setPointSize(28)
            painter.setFont(icon_font)
            center_rect = QRect(0, self.height() // 4, self.width(), 40)
            painter.drawText(center_rect, Qt.AlignmentFlag.AlignCenter, "🎬")

            # Draw Title text centered
            painter.setPen(QColor(255, 255, 255, 230))
            title_font = QFont(self.font())
            title_font.setPointSize(11)
            title_font.setBold(True)
            painter.setFont(title_font)

            text_rect = QRect(12, self.height() // 2 - 10, self.width() - 24, self.height() // 2 - 10)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                self.title
            )
