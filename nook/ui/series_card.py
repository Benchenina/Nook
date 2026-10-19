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

from nook.styles import color, color_rgba
from nook.streaming import site_display_name
from nook.ui.icons import icon, pixmap
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
    remove_requested = pyqtSignal(int)      # series_id (streaming sources only)

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
        is_fav = bool(self.series_data.get("is_favorite", 0))
        self.fav_badge = self._make_pill("heart", "", "#FF5B6E", radius=13)
        self.fav_badge.move(self.CARD_WIDTH - 16 - self.fav_badge.width() - 2, 8)
        self.fav_badge.setVisible(is_fav)

        # Source badge in top left: a local folder vs. a streaming site.
        source_type = (self.series_data.get("source_type") or "local").lower()
        if source_type == "local":
            self.source_badge = self._make_pill("folder", "", "#FFFFFF")
        else:
            self.source_badge = self._make_pill(
                "tv", site_display_name("", source_type), "#FFFFFF"
            )
        self.source_badge.move(8, 8)

        # Episode Count badge in bottom left (above the progress bar)
        ep_count = self.series_data.get("episode_count", 0)
        self.count_badge = self._make_pill("", f"{ep_count} ep{'s' if ep_count != 1 else ''}", "#FFFFFF")
        self.count_badge.move(8, self.POSTER_HEIGHT - 30)

        # Hidden badge if series is hidden
        is_hidden = bool(self.series_data.get("is_hidden", 0))
        self.hidden_badge = self._make_pill("eye-off", "HIDDEN", "#E5A93C", bg="rgba(0, 0, 0, 0.8)")
        self.hidden_badge.move(8, 34)
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
        self.meta_label.setStyleSheet(f"color: {color('text_muted')}; font-size: 11px; font-weight: 500;")
        meta_layout.addWidget(self.meta_label)
        meta_layout.addStretch()

        tags_list = self.series_data.get("tags_list") or []
        if tags_list:
            first_tag = QLabel(tags_list[0], self)
            first_tag.setStyleSheet(f"""
                color: {color('accent')};
                background-color: {color_rgba('accent', 0.14)};
                border-radius: 8px;
                padding: 2px 7px;
                font-size: 10px;
                font-weight: 600;
            """)
            meta_layout.addWidget(first_tag)

        main_layout.addLayout(meta_layout)

    def _make_pill(self, icon_name: str, text: str, color: str,
                   bg: str = "rgba(0, 0, 0, 0.62)", radius: int = 9) -> QFrame:
        """Build a small rounded badge with an optional vector icon."""
        pill = QFrame(self.poster_container)
        pill.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: none; border-radius: {radius}px; }}"
        )
        pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay = QHBoxLayout(pill)
        lay.setContentsMargins(8, 4, 9, 4)
        lay.setSpacing(5)
        if icon_name:
            ic = QLabel(pill)
            ic.setPixmap(pixmap(icon_name, size=13, color=color))
            ic.setStyleSheet("background: transparent;")
            lay.addWidget(ic)
        if text:
            tx = QLabel(text, pill)
            tx.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 700; background: transparent;")
            lay.addWidget(tx)
        pill.adjustSize()
        return pill

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

        open_action = menu.addAction(icon("film", size=16), "Open Series")
        open_action.triggered.connect(lambda: self.clicked.emit(self.series_id))

        play_next_action = menu.addAction(icon("play", size=16), "Play Next Episode")
        play_next_action.triggered.connect(lambda: self.play_next_requested.emit(self.series_id))

        menu.addSeparator()

        is_fav = bool(self.series_data.get("is_favorite", 0))
        fav_action = menu.addAction(
            icon("heart-broken" if is_fav else "heart", size=16),
            "Remove from Favorites" if is_fav else "Add to Favorites",
        )
        fav_action.triggered.connect(lambda: self.favorite_toggled.emit(self.series_id, not is_fav))

        mark_all_action = menu.addAction(icon("check", size=16), "Mark All as Watched")
        mark_all_action.triggered.connect(lambda: self.mark_all_watched.emit(self.series_id, True))

        mark_unwatched_action = menu.addAction(icon("refresh", size=16), "Mark All as Unwatched")
        mark_unwatched_action.triggered.connect(lambda: self.mark_all_watched.emit(self.series_id, False))

        menu.addSeparator()

        custom_action = menu.addAction(icon("gear", size=16), "Customize Series...")
        custom_action.triggered.connect(lambda: self.customize_requested.emit(self.series_id))

        is_hidden = bool(self.series_data.get("is_hidden", 0))
        if is_hidden:
            unhide_action = menu.addAction(icon("eye", size=16), "Unhide Series")
            unhide_action.triggered.connect(lambda: self.unhide_requested.emit(self.series_id))
        else:
            hide_action = menu.addAction(icon("eye-off", size=16), "Hide Series")
            hide_action.triggered.connect(lambda: self.hide_requested.emit(self.series_id))

        menu.addSeparator()

        if self.is_local_source():
            folder_action = menu.addAction(icon("folder-open", size=16), "Open Folder in File Manager")
            folder_action.triggered.connect(self._open_folder_in_file_manager)
        else:
            page_url = self.series_data.get("source_url") or ""
            if page_url:
                import webbrowser

                open_action = menu.addAction(icon("external-link", size=16), "Open Show Page in Browser")
                open_action.triggered.connect(lambda: webbrowser.open(page_url))

            menu.addSeparator()
            remove_action = menu.addAction(icon("trash", size=16), "Remove from Library")
            remove_action.triggered.connect(lambda: self.remove_requested.emit(self.series_id))

        menu.exec(pos)

    def is_local_source(self) -> bool:
        """True for on-disk series, False for imported streaming shows."""
        return (self.series_data.get("source_type") or "local").lower() == "local"

    def _open_folder_in_file_manager(self) -> None:
        folder_path = self.series_data.get("folder_path")
        if not self.is_local_source() or not folder_path or not Path(folder_path).exists():
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
