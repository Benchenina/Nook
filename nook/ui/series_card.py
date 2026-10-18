"""Series Card Widget representing a single series or movie in the library grid."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from nook.ui.widgets.poster_widget import PosterWidget


class SeriesCard(QFrame):
    """Steam/Netflix-inspired cozy rectangular poster card for a series."""

    clicked = pyqtSignal(int)               # series_id
    favorite_toggled = pyqtSignal(int, bool) # series_id, new_state
    customize_requested = pyqtSignal(int)   # series_id
    hide_requested = pyqtSignal(int)        # series_id
    unhide_requested = pyqtSignal(int)      # series_id
    play_next_requested = pyqtSignal(int)   # series_id
    mark_all_watched = pyqtSignal(int, bool)# series_id, watched

    CARD_WIDTH = 180
    POSTER_HEIGHT = 260

    def __init__(self, series_data: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.series_data = series_data
        self.series_id = series_data["id"]
        self.setObjectName("seriesCard")
        self.setFixedWidth(self.CARD_WIDTH)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 10)
        main_layout.setSpacing(8)

        # 1. Poster Container
        self.poster_container = QWidget(self)
        self.poster_container.setFixedSize(self.CARD_WIDTH - 16, self.POSTER_HEIGHT)
        poster_layout = QVBoxLayout(self.poster_container)
        poster_layout.setContentsMargins(0, 0, 0, 0)
        poster_layout.setSpacing(0)

        # Poster Image
        cover_path = self.series_data.get("custom_cover_path") or self.series_data.get("detected_cover_path")
        self.poster_widget = PosterWidget(
            image_path=cover_path,
            title=self.series_data.get("display_title", ""),
            corner_radius=12,
            fixed_size=QSize(self.CARD_WIDTH - 16, self.POSTER_HEIGHT),
            parent=self.poster_container
        )
        poster_layout.addWidget(self.poster_widget)

        # Favorite indicator badge in top right
        self.fav_badge = QLabel(self.poster_container)
        is_fav = bool(self.series_data.get("is_favorite", 0))
        self.fav_badge.setText("♥" if is_fav else "")
        self.fav_badge.setStyleSheet("""
            QLabel {
                color: #E25555;
                font-size: 16px;
                font-weight: bold;
                background-color: rgba(26, 22, 20, 0.7);
                border-radius: 12px;
                padding: 2px 6px;
            }
        """)
        self.fav_badge.move(self.CARD_WIDTH - 16 - 32, 8)
        self.fav_badge.setVisible(is_fav)

        # Episode Count badge in top left
        ep_count = self.series_data.get("episode_count", 0)
        self.count_badge = QLabel(f"{ep_count} ep{'s' if ep_count != 1 else ''}", self.poster_container)
        self.count_badge.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-size: 11px;
                font-weight: 600;
                background-color: rgba(26, 22, 20, 0.75);
                border-radius: 8px;
                padding: 2px 7px;
            }
        """)
        self.count_badge.move(8, 8)

        # Hidden badge if series is hidden
        is_hidden = bool(self.series_data.get("is_hidden", 0))
        self.hidden_badge = QLabel("👁 HIDDEN", self.poster_container)
        self.hidden_badge.setStyleSheet("""
            QLabel {
                color: #E5A93C;
                font-size: 10px;
                font-weight: bold;
                background-color: rgba(26, 22, 20, 0.85);
                border: 1px solid rgba(229, 169, 60, 0.5);
                border-radius: 6px;
                padding: 2px 6px;
            }
        """)
        self.hidden_badge.move(8, 32)
        self.hidden_badge.setVisible(is_hidden)

        # Watched progress bar at the bottom of the poster
        watched_count = self.series_data.get("watched_count", 0)
        self.progress_bar = QProgressBar(self.poster_container)
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(max(1, ep_count))
        self.progress_bar.setValue(watched_count)
        self.progress_bar.setGeometry(0, self.POSTER_HEIGHT - 5, self.CARD_WIDTH - 16, 5)
        self.progress_bar.setVisible(ep_count > 0 and watched_count > 0)

        main_layout.addWidget(self.poster_container)

        # 2. Title Label
        self.title_label = QLabel(self.series_data.get("display_title", "Untitled"), self)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(38)
        font = QFont(self.font())
        font.setPointSize(13)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(self.title_label)

        # 3. Subtitle / Tags info
        meta_layout = QHBoxLayout()
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(4)

        watched_text = f"{watched_count}/{ep_count} watched" if ep_count > 0 else "0 episodes"
        self.meta_label = QLabel(watched_text, self)
        self.meta_label.setStyleSheet("color: #847569; font-size: 11px; font-weight: 500;")
        meta_layout.addWidget(self.meta_label)
        meta_layout.addStretch()

        tags_list = self.series_data.get("tags_list") or []
        if tags_list:
            first_tag = QLabel(tags_list[0], self)
            first_tag.setStyleSheet("""
                color: #E5A93C;
                background-color: rgba(229, 169, 60, 0.12);
                border-radius: 6px;
                padding: 1px 6px;
                font-size: 10px;
                font-weight: 600;
            """)
            meta_layout.addWidget(first_tag)

        main_layout.addLayout(meta_layout)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.series_id)
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.series_id)
        else:
            super().keyPressEvent(event)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)

        open_action = menu.addAction("📖 Open Series")
        open_action.triggered.connect(lambda: self.clicked.emit(self.series_id))

        play_next_action = menu.addAction("▶ Play Next Episode")
        play_next_action.triggered.connect(lambda: self.play_next_requested.emit(self.series_id))

        menu.addSeparator()

        is_fav = bool(self.series_data.get("is_favorite", 0))
        fav_text = "💔 Remove from Favorites" if is_fav else "♥ Add to Favorites"
        fav_action = menu.addAction(fav_text)
        fav_action.triggered.connect(lambda: self.favorite_toggled.emit(self.series_id, not is_fav))

        mark_all_action = menu.addAction("✓ Mark All as Watched")
        mark_all_action.triggered.connect(lambda: self.mark_all_watched.emit(self.series_id, True))

        mark_unwatched_action = menu.addAction("↺ Mark All as Unwatched")
        mark_unwatched_action.triggered.connect(lambda: self.mark_all_watched.emit(self.series_id, False))

        menu.addSeparator()

        custom_action = menu.addAction("⚙ Customize Series...")
        is_hidden = bool(self.series_data.get("is_hidden", 0))
        if is_hidden:
            unhide_action = menu.addAction("👁 Unhide Series")
            unhide_action.triggered.connect(lambda: self.unhide_requested.emit(self.series_id))
        else:
            hide_action = menu.addAction("👁 Hide Series")
            hide_action.triggered.connect(lambda: self.hide_requested.emit(self.series_id))

        folder_action = menu.addAction("📁 Open Folder in File Manager")
        folder_action.triggered.connect(self._open_folder_in_file_manager)

        menu.exec(pos)

    def _open_folder_in_file_manager(self) -> None:
        folder_path = self.series_data.get("folder_path")
        if not folder_path or not Path(folder_path).exists():
            return

        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(folder_path)
            elif system == "Darwin":
                subprocess.Popen(["open", folder_path])
            else:
                subprocess.Popen(["xdg-open", folder_path])
        except Exception:
            pass
