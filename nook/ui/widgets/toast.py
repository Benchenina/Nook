"""Cozy floating toast notification widget for Nook."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, QPropertyAnimation, QRect, QTimer, Qt
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget


class ToastNotification(QWidget):
    """Floating pill toast notification that gently fades in and out."""

    def __init__(self, parent: QWidget, message: str, duration_ms: int = 3000):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)

        self.label = QLabel(message, self)
        self.label.setStyleSheet("color: #FFFFFF; font-weight: 600; font-size: 13px;")
        layout.addWidget(self.label)

        self.setStyleSheet("""
            ToastNotification {
                background-color: rgba(30, 24, 20, 0.92);
                border: 1px solid rgba(229, 169, 60, 0.4);
                border-radius: 18px;
            }
        """)

        # Opacity animation
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_anim = QPropertyAnimation(self.opacity_effect, b"opacity")

        self.adjustSize()
        self._position_toast()

        # Timer to dismiss
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fade_out)

        self.fade_in()
        self.timer.start(duration_ms)

    def _position_toast(self) -> None:
        if self.parent():
            parent_rect = self.parent().rect()
            x = (parent_rect.width() - self.width()) // 2
            y = parent_rect.height() - self.height() - 35
            self.move(QPoint(x, y))

    def fade_in(self) -> None:
        self.show()
        self.opacity_anim.stop()
        self.opacity_anim.setDuration(250)
        self.opacity_anim.setStartValue(0.0)
        self.opacity_anim.setEndValue(1.0)
        self.opacity_anim.start()

    def fade_out(self) -> None:
        self.opacity_anim.stop()
        self.opacity_anim.setDuration(350)
        self.opacity_anim.setStartValue(1.0)
        self.opacity_anim.setEndValue(0.0)
        self.opacity_anim.finished.connect(self.deleteLater)
        self.opacity_anim.start()

    @classmethod
    def show_toast(cls, parent: QWidget, message: str, duration_ms: int = 3000) -> ToastNotification:
        return cls(parent, message, duration_ms)
