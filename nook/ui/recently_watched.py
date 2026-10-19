"""Recently Watched strip showing resumable episodes as a compact top bar."""

from __future__ import annotations

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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nook.player import MediaPlayer
from nook.styles import color
from nook.ui.icons import icon, pixmap
from nook.ui.widgets.poster_widget import PosterWidget


class RecentlyWatchedCard(QFrame):
    """Compact card representing an episode in the Continue Watching strip."""

    resume_requested = pyqtSignal(int)  # episode_id
    series_clicked = pyqtSignal(int)    # series_id
    remove_requested = pyqtSignal(int)  # episode_id

    CARD_WIDTH = 252
    CARD_HEIGHT = 64

    def __init__(self, item_data: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.item_data = item_data
        self.episode_id = item_data["id"]
        self.series_id = item_data["series_id"]

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setObjectName("episodeRow")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 6, 6)
        layout.setSpacing(8)

        # 1. Mini Poster Thumbnail
        cover_path = self.item_data.get("series_custom_cover") or self.item_data.get("series_detected_cover")
        self.poster = PosterWidget(
            image_path=cover_path,
            title=self.item_data.get("series_title", ""),
            corner_radius=6,
            fixed_size=QSize(40, 52),
            parent=self
        )
        layout.addWidget(self.poster)

        # 2. Middle Text & Progress
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        # Series Title (ignored size policy so long names never stretch the card)
        self.series_label = QLabel(self.item_data.get("series_title", "Untitled"), self)
        series_font = QFont(self.font())
        series_font.setPointSize(11)
        series_font.setBold(True)
        self.series_label.setFont(series_font)
        self.series_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text_layout.addWidget(self.series_label)

        # Episode Title
        ep_title = self.item_data.get("clean_title") or self.item_data.get("file_name", "Episode")
        self.ep_label = QLabel(ep_title, self)
        self.ep_label.setStyleSheet(f"color: {color('text_muted')}; font-size: 10px;")
        self.ep_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text_layout.addWidget(self.ep_label)

        # Progress bar & timestamp
        pos_sec = self.item_data.get("playback_position", 0)
        dur_sec = self.item_data.get("duration_seconds", 0)

        prog_layout = QHBoxLayout()
        prog_layout.setSpacing(6)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedHeight(3)
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
        self.time_label.setStyleSheet(f"color: {color('text_muted')}; font-size: 9px; font-weight: 500;")
        prog_layout.addWidget(self.time_label)

        text_layout.addLayout(prog_layout)
        layout.addLayout(text_layout, stretch=1)

        # 3. Resume Button
        self.resume_btn = QPushButton(self)
        self.resume_btn.setFixedSize(30, 30)
        self.resume_btn.setObjectName("primaryBtn")
        self.resume_btn.setIcon(icon("play", size=14, color="#0A0A0A"))
        self.resume_btn.setIconSize(QSize(14, 14))
        self.resume_btn.setToolTip("Resume episode")
        self.resume_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.resume_btn.clicked.connect(lambda: self.resume_requested.emit(self.episode_id))
        layout.addWidget(self.resume_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # 4. Remove-from-history Button
        self.remove_btn = QPushButton(self)
        self.remove_btn.setFixedSize(20, 20)
        self.remove_btn.setObjectName("removeHistoryBtn")
        self.remove_btn.setIcon(icon("close", size=11, color=color("text_muted")))
        self.remove_btn.setIconSize(QSize(11, 11))
        self.remove_btn.setToolTip("Remove from Continue Watching")
        self.remove_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.episode_id))
        layout.addWidget(self.remove_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # If clicked outside the buttons, open series detail
            self.series_clicked.emit(self.series_id)
        super().mousePressEvent(event)


class RecentlyWatchedCarousel(QWidget):
    """Compact horizontal strip for recently watched episodes.

    The widget sizes itself to exactly one row of episode cards so it never
    steals vertical space from the library grid below it.
    """

    resume_episode = pyqtSignal(int)
    open_series = pyqtSignal(int)
    remove_episode = pyqtSignal(int)

    # Room reserved for the horizontal scrollbar when cards overflow.
    SCROLLBAR_ALLOWANCE = 16

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # "Maximum" caps the height at the size hint, so the surrounding
        # vertical layout can never stretch this strip into a big block.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_ui()

    def refresh_icons(self) -> None:
        """Re-render header icon after a theme change."""
        self.carousel_icon.setPixmap(pixmap("clock", size=15))

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 2, 4, 8)
        main_layout.setSpacing(12)

        # Compact inline title, vertically centred next to the cards.
        self.header_widget = QWidget(self)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self.carousel_icon = QLabel(self.header_widget)
        self.carousel_icon.setPixmap(pixmap("clock", size=15))
        header_layout.addWidget(self.carousel_icon)

        self.title_label = QLabel("Continue Watching", self.header_widget)
        font = QFont(self.font())
        font.setPointSize(12)
        font.setBold(True)
        self.title_label.setFont(font)
        header_layout.addWidget(self.title_label)

        main_layout.addWidget(self.header_widget, 0, Qt.AlignmentFlag.AlignVCenter)

        # Scroll Area for horizontal cards - exactly one card row tall.
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setFixedHeight(
            RecentlyWatchedCard.CARD_HEIGHT + self.SCROLLBAR_ALLOWANCE
        )
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.cards_container = QWidget()
        self.cards_layout = QHBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, stretch=1)

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
            card.remove_requested.connect(self.remove_episode.emit)
            # Insert before the trailing stretch
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
