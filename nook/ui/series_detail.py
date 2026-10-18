"""Series Detail View with folder view, episodes list/grid, and watch tracking."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nook.database import Database
from nook.player import MediaPlayer
from nook.ui.customization_modal import CustomizationModal
from nook.ui.scraper_dialog import ScraperDialog
from nook.ui.widgets.flow_layout import FlowLayout
from nook.ui.widgets.poster_widget import PosterWidget
from nook.ui.widgets.toast import ToastNotification


class EpisodeRowWidget(QFrame):
    """Detailed list row for a single episode."""

    play_requested = pyqtSignal(int, bool)    # episode_id, resume
    watched_toggled = pyqtSignal(int, bool)  # episode_id, is_watched
    data_changed = pyqtSignal()

    def __init__(self, ep_data: Dict[str, Any], db: Database, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ep_data = ep_data
        self.episode_id = ep_data["id"]
        self.db = db
        self.setObjectName("episodeRow")

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)

        # 1. Watched Checkbox
        self.watched_chk = QCheckBox(self)
        self.watched_chk.setChecked(bool(self.ep_data.get("watched", 0)))
        self.watched_chk.setToolTip("Toggle Watched status")
        self.watched_chk.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.watched_chk.toggled.connect(self._on_watched_toggled)
        layout.addWidget(self.watched_chk)

        # 2. Episode / Season Number Badge
        season_num = self.ep_data.get("season_number", 0)
        ep_num = self.ep_data.get("episode_number", 0)
        if season_num > 0 and ep_num > 0:
            badge_text = f"S{season_num:02d}E{ep_num:02d}"
        elif ep_num > 0:
            badge_text = f"EP {ep_num:02d}"
        else:
            badge_text = "FILE"

        badge = QLabel(badge_text, self)
        badge.setStyleSheet("""
            QLabel {
                background-color: #3E3530;
                color: #E5A93C;
                font-weight: 700;
                font-size: 11px;
                border-radius: 6px;
                padding: 3px 8px;
            }
        """)
        layout.addWidget(badge)

        # 3. Clean Title & File Name
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)

        self.title_label = QLabel(self.ep_data.get("clean_title") or self.ep_data.get("file_name", "Episode"), self)
        t_font = QFont(self.font())
        t_font.setPointSize(13)
        t_font.setBold(True)
        self.title_label.setFont(t_font)
        title_box.addWidget(self.title_label)

        file_name = self.ep_data.get("file_name", "")
        self.sub_label = QLabel(file_name, self)
        self.sub_label.setStyleSheet("color: #847569; font-size: 11px;")
        title_box.addWidget(self.sub_label)

        layout.addLayout(title_box, stretch=3)

        # 4. File Size
        size_bytes = self.ep_data.get("file_size", 0)
        size_str = self._format_size(size_bytes)
        size_lbl = QLabel(size_str, self)
        size_lbl.setStyleSheet("color: #847569; font-size: 11px; font-weight: 500;")
        layout.addWidget(size_lbl)

        # 5. Playback progress bar & timestamp
        prog_widget = QWidget(self)
        prog_widget.setFixedWidth(130)
        prog_box = QVBoxLayout(prog_widget)
        prog_box.setContentsMargins(0, 0, 0, 0)
        prog_box.setSpacing(3)

        pos_sec = self.ep_data.get("playback_position", 0)
        dur_sec = self.ep_data.get("duration_seconds", 0)

        self.progress_bar = QProgressBar(prog_widget)
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setTextVisible(False)
        if dur_sec > 0:
            self.progress_bar.setMaximum(dur_sec)
            self.progress_bar.setValue(min(pos_sec, dur_sec))
            time_str = f"{MediaPlayer.format_timestamp(pos_sec)} / {MediaPlayer.format_timestamp(dur_sec)}"
        else:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(100 if self.ep_data.get("watched") else (50 if pos_sec > 0 else 0))
            time_str = MediaPlayer.format_timestamp(pos_sec) if pos_sec > 0 else ("Watched" if self.ep_data.get("watched") else "Unwatched")

        prog_box.addWidget(self.progress_bar)

        self.time_lbl = QLabel(time_str, prog_widget)
        self.time_lbl.setStyleSheet("color: #847569; font-size: 10px; font-weight: 500;")
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prog_box.addWidget(self.time_lbl)

        layout.addWidget(prog_widget)

        # 6. Action buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        # Resume / Play Button
        self.play_btn = QPushButton("▶ Resume" if pos_sec > 0 and not self.ep_data.get("watched") else "▶ Play", self)
        if pos_sec > 0 and not self.ep_data.get("watched"):
            self.play_btn.setObjectName("primaryBtn")
        else:
            self.play_btn.setObjectName("secondaryBtn")
        self.play_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.play_btn.clicked.connect(lambda: self.play_requested.emit(self.episode_id, True))
        btn_box.addWidget(self.play_btn)

        # More Options button
        more_btn = QPushButton("⋯", self)
        more_btn.setObjectName("iconBtn")
        more_btn.setFixedSize(32, 32)
        more_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        more_btn.clicked.connect(lambda: self._show_context_menu(more_btn.mapToGlobal(QPoint(0, more_btn.height()))))
        btn_box.addWidget(more_btn)

        layout.addLayout(btn_box)

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        if num_bytes <= 0:
            return ""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if num_bytes < 1024.0:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"

    def _on_watched_toggled(self, checked: bool) -> None:
        self.db.toggle_episode_watched(self.episode_id, checked)
        self.watched_toggled.emit(self.episode_id, checked)
        self.data_changed.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)

        pos_sec = self.ep_data.get("playback_position", 0)
        if pos_sec > 0:
            resume_act = menu.addAction(f"▶ Resume from {MediaPlayer.format_timestamp(pos_sec)}")
            resume_act.triggered.connect(lambda: self.play_requested.emit(self.episode_id, True))

        play_start_act = menu.addAction("▶ Play from Beginning")
        play_start_act.triggered.connect(lambda: self.play_requested.emit(self.episode_id, False))

        menu.addSeparator()

        set_time_act = menu.addAction("⏱ Set Resume Timestamp...")
        set_time_act.triggered.connect(self._prompt_set_timestamp)

        reset_time_act = menu.addAction("↺ Reset Playback Progress")
        reset_time_act.triggered.connect(self._reset_progress)

        menu.addSeparator()

        is_watched = bool(self.ep_data.get("watched", 0))
        toggle_watched_act = menu.addAction("○ Mark Unwatched" if is_watched else "✓ Mark Watched")
        toggle_watched_act.triggered.connect(lambda: self._on_watched_toggled(not is_watched))

        folder_act = menu.addAction("📁 Open File Location")
        folder_act.triggered.connect(self._open_file_location)

        menu.exec(pos)

    def _prompt_set_timestamp(self) -> None:
        curr = MediaPlayer.format_timestamp(self.ep_data.get("playback_position", 0))
        text, ok = QInputDialog.getText(
            self,
            "Set Resume Timestamp",
            "Enter timestamp (HH:MM:SS, MM:SS, or total seconds):",
            text=curr
        )
        if ok and text:
            seconds = self._parse_time_input(text.strip())
            self.db.update_episode_progress(self.episode_id, seconds)
            self.data_changed.emit()

    def _reset_progress(self) -> None:
        self.db.update_episode_progress(self.episode_id, 0, watched=False)
        self.data_changed.emit()

    @staticmethod
    def _parse_time_input(text: str) -> int:
        if text.isdigit():
            return int(text)
        parts = text.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
        return 0

    def _open_file_location(self) -> None:
        file_path = Path(self.ep_data.get("file_path", ""))
        if not file_path.exists():
            return
        folder = file_path.parent
        system = platform.system()
        try:
            if system == "Windows":
                subprocess.Popen(f'explorer /select,"{file_path}"')
            elif system == "Darwin":
                subprocess.Popen(["open", "-R", str(file_path)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass


class SeriesDetailView(QWidget):
    """Full detail view for a single series showing metadata and episode browser."""

    back_requested = pyqtSignal()
    series_updated = pyqtSignal(int)

    def __init__(self, db: Database, media_player: MediaPlayer, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self.media_player = media_player
        self.series_id: Optional[int] = None
        self.series_data: Dict[str, Any] = {}
        self.episodes: List[Dict[str, Any]] = []

        self.view_mode = self.db.get_setting("detail_view_mode", "list")

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 20)
        main_layout.setSpacing(16)

        # 1. Back button header
        top_bar = QHBoxLayout()
        self.back_btn = QPushButton("← Back to Library", self)
        self.back_btn.setObjectName("secondaryBtn")
        self.back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.back_btn.clicked.connect(self.back_requested.emit)
        top_bar.addWidget(self.back_btn)
        top_bar.addStretch()

        main_layout.addLayout(top_bar)

        # 2. Hero Header Card
        self.hero_card = QFrame(self)
        self.hero_card.setObjectName("episodeRow")
        hero_layout = QHBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(20, 20, 20, 20)
        hero_layout.setSpacing(22)

        # Poster
        self.hero_poster = PosterWidget(
            image_path=None,
            title="",
            corner_radius=12,
            fixed_size=QSize(130, 190),
            parent=self.hero_card
        )
        hero_layout.addWidget(self.hero_poster)

        # Info Box
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(8)

        # Title & Favorite button
        title_row = QHBoxLayout()
        self.title_lbl = QLabel("Series Title", self.hero_card)
        t_font = QFont(self.font())
        t_font.setPointSize(20)
        t_font.setBold(True)
        self.title_lbl.setFont(t_font)
        title_row.addWidget(self.title_lbl)

        self.fav_btn = QPushButton("♥ Favorite", self.hero_card)
        self.fav_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.fav_btn.clicked.connect(self._toggle_favorite)
        title_row.addWidget(self.fav_btn)
        title_row.addStretch()

        info_layout.addLayout(title_row)

        # Tags Pills container
        self.tags_container = QWidget(self.hero_card)
        self.tags_layout = QHBoxLayout(self.tags_container)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(8)
        self.tags_layout.addStretch()
        info_layout.addWidget(self.tags_container)

        # Description / synopsis
        self.desc_lbl = QLabel(self.hero_card)
        self.desc_lbl.setStyleSheet("color: #BFAFA1; font-size: 13px; line-height: 1.4;")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setMaximumHeight(65)
        info_layout.addWidget(self.desc_lbl)

        # Watch Stats & Progress Bar
        stats_box = QVBoxLayout()
        stats_box.setSpacing(4)

        stats_row = QHBoxLayout()
        self.stats_lbl = QLabel("0 episodes • 0 watched", self.hero_card)
        self.stats_lbl.setStyleSheet("color: #847569; font-size: 12px; font-weight: 600;")
        stats_row.addWidget(self.stats_lbl)
        stats_row.addStretch()
        stats_box.addLayout(stats_row)

        self.overall_progress = QProgressBar(self.hero_card)
        self.overall_progress.setFixedHeight(6)
        self.overall_progress.setTextVisible(False)
        stats_box.addWidget(self.overall_progress)

        info_layout.addLayout(stats_box)

        # Action Buttons row
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.play_next_btn = QPushButton("▶ Play Next Episode", self.hero_card)
        self.play_next_btn.setObjectName("primaryBtn")
        self.play_next_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.play_next_btn.clicked.connect(self._play_next_episode)
        action_row.addWidget(self.play_next_btn)

        self.customize_btn = QPushButton("⚙ Customize", self.hero_card)
        self.customize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.customize_btn.clicked.connect(self._open_customization)
        action_row.addWidget(self.customize_btn)

        self.scrape_btn = QPushButton("🌐 Online Info", self.hero_card)
        self.scrape_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.scrape_btn.clicked.connect(self._open_scraper)
        action_row.addWidget(self.scrape_btn)

        self.open_folder_btn = QPushButton("📁 Folder", self.hero_card)
        self.open_folder_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.open_folder_btn.clicked.connect(self._open_series_folder)
        action_row.addWidget(self.open_folder_btn)

        self.unhide_btn = QPushButton("👁 Unhide Series", self.hero_card)
        self.unhide_btn.setObjectName("secondaryBtn")
        self.unhide_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.unhide_btn.clicked.connect(self._unhide_series)
        self.unhide_btn.setVisible(False)
        action_row.addWidget(self.unhide_btn)

        action_row.addStretch()
        info_layout.addLayout(action_row)

        hero_layout.addLayout(info_layout, stretch=1)
        main_layout.addWidget(self.hero_card)

        # 3. Episode List Toolbar (View Toggle & Bulk actions)
        toolbar = QHBoxLayout()
        ep_header = QLabel("Episodes", self)
        e_font = QFont(self.font())
        e_font.setPointSize(16)
        e_font.setBold(True)
        ep_header.setFont(e_font)
        toolbar.addWidget(ep_header)

        toolbar.addStretch()

        # Mark all watched / unwatched
        mark_all_btn = QPushButton("✓ Mark All Watched", self)
        mark_all_btn.setObjectName("secondaryBtn")
        mark_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        mark_all_btn.clicked.connect(lambda: self._mark_all_watched(True))
        toolbar.addWidget(mark_all_btn)

        mark_unwatched_btn = QPushButton("↺ Mark All Unwatched", self)
        mark_unwatched_btn.setObjectName("secondaryBtn")
        mark_unwatched_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        mark_unwatched_btn.clicked.connect(lambda: self._mark_all_watched(False))
        toolbar.addWidget(mark_unwatched_btn)

        # View Mode Toggle: List vs Grid
        self.mode_list_btn = QPushButton("≡ List", self)
        self.mode_list_btn.setCheckable(True)
        self.mode_list_btn.setChecked(self.view_mode == "list")
        self.mode_list_btn.clicked.connect(lambda: self._set_view_mode("list"))
        toolbar.addWidget(self.mode_list_btn)

        self.mode_grid_btn = QPushButton("⊞ Grid", self)
        self.mode_grid_btn.setCheckable(True)
        self.mode_grid_btn.setChecked(self.view_mode == "grid")
        self.mode_grid_btn.clicked.connect(lambda: self._set_view_mode("grid"))
        toolbar.addWidget(self.mode_grid_btn)

        main_layout.addLayout(toolbar)

        # 4. Episodes Scroll Area
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.episodes_container = QWidget()
        self.scroll_area.setWidget(self.episodes_container)
        main_layout.addWidget(self.scroll_area)

    def load_series(self, series_id: int) -> None:
        """Load and display details for a given series."""
        self.series_id = series_id
        self.series_data = self.db.get_series_by_id(series_id) or {}
        self.episodes = self.db.get_episodes_for_series(series_id)

        # Update Hero Section
        title = self.series_data.get("display_title", "Untitled")
        self.title_lbl.setText(title)

        cover_path = self.series_data.get("custom_cover_path") or self.series_data.get("detected_cover_path")
        self.hero_poster.set_image(cover_path, title=title)

        is_fav = bool(self.series_data.get("is_favorite", 0))
        self.fav_btn.setText("♥ Favorited" if is_fav else "♡ Favorite")
        self.fav_btn.setStyleSheet("color: #E25555; font-weight: bold;" if is_fav else "")

        is_hidden = bool(self.series_data.get("is_hidden", 0))
        self.unhide_btn.setVisible(is_hidden)

        desc = self.series_data.get("description", "")
        self.desc_lbl.setText(desc if desc else "No synopsis available. Click 'Online Info' to fetch metadata automatically.")
        self.desc_lbl.setStyleSheet("color: #BFAFA1; font-size: 13px;" if desc else "color: #847569; font-style: italic;")

        # Populate Tags
        while self.tags_layout.count() > 1:
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tags_list = self.series_data.get("tags_list") or []
        for t in tags_list:
            pill = QLabel(t, self.tags_container)
            pill.setObjectName("tagPill")
            self.tags_layout.insertWidget(self.tags_layout.count() - 1, pill)

        # Update stats
        ep_count = len(self.episodes)
        watched_count = sum(1 for e in self.episodes if e.get("watched"))
        self.stats_lbl.setText(f"{ep_count} episodes • {watched_count} watched ({int((watched_count/max(1, ep_count))*100)}%)")
        self.overall_progress.setMaximum(max(1, ep_count))
        self.overall_progress.setValue(watched_count)

        # Render Episodes
        self._render_episodes()

    def _set_view_mode(self, mode: str) -> None:
        self.view_mode = mode
        self.mode_list_btn.setChecked(mode == "list")
        self.mode_grid_btn.setChecked(mode == "grid")
        self.db.set_setting("detail_view_mode", mode)
        self._render_episodes()

    def _render_episodes(self) -> None:
        # Clear existing layout
        old_layout = self.episodes_container.layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(old_layout)

        if not self.episodes:
            empty_layout = QVBoxLayout(self.episodes_container)
            empty_lbl = QLabel("No video files detected inside this series folder.", self.episodes_container)
            empty_lbl.setStyleSheet("color: #847569; font-size: 14px; padding: 40px;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(empty_lbl)
            return

        if self.view_mode == "grid":
            # Grid layout for episodes
            layout = FlowLayout(self.episodes_container, margin=0, h_spacing=12, v_spacing=12)
            for ep in self.episodes:
                card = self._create_grid_episode_card(ep)
                layout.addWidget(card)
        else:
            # Detailed List view
            layout = QVBoxLayout(self.episodes_container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            for ep in self.episodes:
                row = EpisodeRowWidget(ep, self.db, self.episodes_container)
                row.play_requested.connect(self._play_episode)
                row.data_changed.connect(lambda: self.load_series(self.series_id))
                layout.addWidget(row)
            layout.addStretch()

    def _create_grid_episode_card(self, ep: Dict[str, Any]) -> QWidget:
        """Create a compact card for grid view."""
        card = QFrame(self.episodes_container)
        card.setObjectName("episodeRow")
        card.setFixedSize(220, 100)
        card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        l = QVBoxLayout(card)
        l.setContentsMargins(12, 10, 12, 10)
        l.setSpacing(4)

        header = QHBoxLayout()
        ep_num = ep.get("episode_number", 0)
        num_lbl = QLabel(f"EP {ep_num:02d}" if ep_num > 0 else "FILE", card)
        num_lbl.setStyleSheet("color: #E5A93C; font-weight: bold; font-size: 11px;")
        header.addWidget(num_lbl)
        header.addStretch()

        if ep.get("watched"):
            w_lbl = QLabel("✓ Watched", card)
            w_lbl.setStyleSheet("color: #8A9A86; font-size: 10px; font-weight: bold;")
            header.addWidget(w_lbl)
        header.addStretch()
        l.addLayout(header)

        title = QLabel(ep.get("clean_title") or ep.get("file_name", ""), card)
        title.setWordWrap(True)
        title.setFont(QFont(self.font().family(), 11, QFont.Weight.Bold))
        l.addWidget(title)

        l.addStretch()

        play_btn = QPushButton("▶ Play", card)
        play_btn.setObjectName("primaryBtn" if not ep.get("watched") else "secondaryBtn")
        play_btn.setFixedHeight(26)
        play_btn.clicked.connect(lambda: self._play_episode(ep["id"], True))
        l.addWidget(play_btn)

        return card

    def _play_episode(self, episode_id: int, resume: bool = True) -> None:
        success, err = self.media_player.play_episode(episode_id, resume=resume)
        if not success:
            ToastNotification.show_toast(self.window(), f"Player Error: {err}", duration_ms=4000)
        else:
            # Refresh details
            self.load_series(self.series_id)
            self.series_updated.emit(self.series_id)

    def _play_next_episode(self) -> None:
        """Find and play the first unwatched episode, or the first episode."""
        if not self.episodes:
            return
        # Find first unwatched
        target = next((e for e in self.episodes if not e.get("watched")), self.episodes[0])
        self._play_episode(target["id"], resume=True)

    def _toggle_favorite(self) -> None:
        is_fav = not bool(self.series_data.get("is_favorite", 0))
        self.db.set_series_favorite(self.series_id, is_fav)
        self.load_series(self.series_id)
        self.series_updated.emit(self.series_id)

    def _unhide_series(self) -> None:
        self.db.set_series_hidden(self.series_id, False)
        self.load_series(self.series_id)
        self.series_updated.emit(self.series_id)
        ToastNotification.show_toast(self.window(), "Series unhidden and restored to library grid.")

    def _mark_all_watched(self, watched: bool) -> None:
        self.db.mark_all_episodes_watched(self.series_id, watched=watched)
        self.load_series(self.series_id)
        self.series_updated.emit(self.series_id)
        status_text = "All episodes marked as watched." if watched else "All episodes marked as unwatched."
        ToastNotification.show_toast(self.window(), status_text)

    def _open_customization(self) -> None:
        modal = CustomizationModal(self.series_id, self.db, self)
        modal.customization_saved.connect(lambda sid: (self.load_series(sid), self.series_updated.emit(sid)))
        modal.exec()

    def _open_scraper(self) -> None:
        dialog = ScraperDialog(self.series_id, self.db, self)
        dialog.metadata_applied.connect(lambda sid: (self.load_series(sid), self.series_updated.emit(sid)))
        dialog.exec()

    def _open_series_folder(self) -> None:
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
        except Exception as e:
            ToastNotification.show_toast(self.window(), f"Could not open folder: {str(e)}")
