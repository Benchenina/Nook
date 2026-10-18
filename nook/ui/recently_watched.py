"""Recently Watched Carousel showing recently played episodes with progress bars and resume buttons."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nook.player import MediaPlayer
from nook.ui.widgets.poster_widget import PosterWidget


class RecentlyWatchedCard(QFrame):
    """Card widget representing an episode in the recently watched carousel."""

    resume_requested = pyqtSignal(int)  # episode_id
    series_clicked = pyqtSignal(int)    # series_id

    def __init__(self, item_data: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.item_data = item_data
        self.episode_id = item_data["id"]
        self.series_id = item_data["series_id"]

        self.setFixedWidth(290)
        self.setFixedHeight(84)
        self.setObjectName("episodeRow")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 10, 6)
        layout.setSpacing(12)

        # 1. Mini Poster Thumbnail
        cover_path = self.item_data.get("series_custom_cover") or self.item_data.get("series_detected_cover")
        self.poster = PosterWidget(
            image_path=cover_path,
            title=self.item_data.get("series_title", ""),
            corner_radius=8,
            fixed_size=QSize(48, 70),
            parent=self
        )
        layout.addWidget(self.poster)

        # 2. Middle Text & Progress
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 2, 0, 2)
        text_layout.setSpacing(2)

        # Series Title
        self.series_label = QLabel(self.item_data.get("series_title", "Untitled"), self)
        series_font = QFont(self.font())
        series_font.setPointSize(12)
        series_font.setBold(True)
        self.series_label.setFont(series_font)
        text_layout.addWidget(self.series_label)

        # Episode Title
        ep_title = self.item_data.get("clean_title") or self.item_data.get("file_name", "Episode")
        self.ep_label = QLabel(ep_title, self)
        self.ep_label.setStyleSheet("color: #847569; font-size: 11px;")
        text_layout.addWidget(self.ep_label)

        # Progress bar & timestamp
        pos_sec = self.item_data.get("playback_position", 0)
        dur_sec = self.item_data.get("duration_seconds", 0)

        prog_layout = QHBoxLayout()
        prog_layout.setSpacing(6)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        if dur_sec > 0:
            self.progress_bar.setMaximum(dur_sec)
            self.progress_bar.setValue(min(pos_sec, dur_sec))
            time_text = f"{MediaPlayer.format_timestamp(pos_sec)} / {MediaPlayer.format_timestamp(dur_sec)}"
        else:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(100 if self.item_data.get("watched") else (50 if pos_sec > 0 else 0))
            time_text = MediaPlayer.format_timestamp(pos_sec) if pos_sec > 0 else ("Watched" if self.item_data.get("watched") else "Played")

        prog_layout.addWidget(self.progress_bar)

        self.time_label = QLabel(time_text, self)
        self.time_label.setStyleSheet("color: #847569; font-size: 10px; font-weight: 500;")
        prog_layout.addWidget(self.time_label)

        text_layout.addLayout(prog_layout)
        layout.addLayout(text_layout)

        # 3. Resume Button
        self.resume_btn = QPushButton("▶", self)
        self.resume_btn.setFixedSize(36, 36)
        self.resume_btn.setObjectName("primaryBtn")
        self.resume_btn.setToolTip("Resume episode")
        self.resume_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.resume_btn.clicked.connect(lambda: self.resume_requested.emit(self.episode_id))
        layout.addWidget(self.resume_btn)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # If clicked outside the button, open series detail
            self.series_clicked.emit(self.series_id)
        super().mousePressEvent(event)


class RecentlyWatchedCarousel(QWidget):
    """Horizontal carousel container for recently watched episodes."""

    resume_episode = pyqtSignal(int)
    open_series = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 10)
        main_layout.setSpacing(8)

        # Header with title
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 0, 4, 0)

        title = QLabel("⏳ Continue Watching", self)
        font = QFont(self.font())
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        header_layout.addWidget(title)
        header_layout.addStretch()

        main_layout.addLayout(header_layout)

        # Scroll Area for horizontal cards
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setFixedHeight(102)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.cards_container = QWidget()
        self.cards_layout = QHBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area)

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        """Populate carousel cards."""
        # Clear existing items
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not items:
            self.setVisible(False)
            return

        self.setVisible(True)
        for ep in items:
            card = RecentlyWatchedCard(ep, self.cards_container)
            card.resume_requested.connect(self.resume_episode.emit)
            card.series_clicked.connect(self.open_series.emit)
            # Insert before the trailing stretch
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
