"""Library View displaying Recently Watched carousel, filter/sort bar, and responsive series grid."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nook.database import Database
from nook.player import MediaPlayer, open_url
from nook.ui.customization_modal import CustomizationModal
from nook.styles import color
from nook.ui.icons import icon, pixmap
from nook.ui.recently_watched import RecentlyWatchedCarousel
from nook.ui.series_card import SeriesCard
from nook.ui.widgets.flow_layout import FlowLayout
from nook.ui.widgets.toast import ToastNotification


class LibraryView(QWidget):
    """Main library grid view with tag filtering, sorting, and recently watched carousel."""

    series_selected = pyqtSignal(int)
    open_settings_requested = pyqtSignal()

    def __init__(
        self,
        db: Database,
        media_player: MediaPlayer,
        only_favorites: bool = False,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.db = db
        self.media_player = media_player
        self.only_favorites = only_favorites

        self.current_tag: str = "All"
        self.current_sort: str = "title"
        self.search_query: str = ""
        self.show_hidden: bool = False

        self._cards: List[SeriesCard] = []

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 14, 20, 14)
        main_layout.setSpacing(12)

        # 1. Recently Watched Carousel (only on main library tab, not on favorites tab)
        if not self.only_favorites:
            self.carousel = RecentlyWatchedCarousel(self)
            self.carousel.resume_episode.connect(self._resume_episode)
            self.carousel.open_series.connect(self.series_selected.emit)
            self.carousel.remove_episode.connect(self._remove_from_history)
            main_layout.addWidget(self.carousel)
        else:
            self.carousel = None

        # 2. Filter & Sort Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        # Tag pills scroll area
        self.tags_scroll = QScrollArea(self)
        self.tags_scroll.setFixedHeight(38)
        self.tags_scroll.setWidgetResizable(True)
        self.tags_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tags_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tags_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.tags_container = QWidget()
        self.tags_layout = QHBoxLayout(self.tags_container)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(8)
        self.tags_layout.addStretch()

        self.tags_scroll.setWidget(self.tags_container)
        toolbar.addWidget(self.tags_scroll, stretch=1)

        # Show Hidden Toggle Button
        self.show_hidden_btn = QPushButton("Hidden", self)
        self.show_hidden_btn.setObjectName("secondaryBtn")
        self.show_hidden_btn.setCheckable(True)
        self.show_hidden_btn.setChecked(False)
        self.show_hidden_btn.setIconSize(QSize(16, 16))
        self.show_hidden_btn.setToolTip("Toggle displaying hidden items in library")
        self.show_hidden_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.show_hidden_btn.clicked.connect(self._toggle_show_hidden)
        toolbar.addWidget(self.show_hidden_btn)

        # Sort dropdown
        sort_lbl = QLabel("Sort by:", self)
        sort_lbl.setStyleSheet(f"color: {color('text_muted')}; font-weight: 500; font-size: 13px;")
        toolbar.addWidget(sort_lbl)

        self.sort_combo = QComboBox(self)
        self.sort_combo.addItem("A-Z (Title)", "title")
        self.sort_combo.addItem("Z-A (Title)", "title_desc")
        self.sort_combo.addItem("Recently Added", "recent_added")
        self.sort_combo.addItem("Most Watched", "most_watched")
        self.sort_combo.addItem("Recently Watched", "recent_watched")
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        toolbar.addWidget(self.sort_combo)

        main_layout.addLayout(toolbar)

        # 3. Main Grid Scroll Area
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_container = QWidget()
        self.grid_layout = FlowLayout(self.grid_container, margin=4, h_spacing=18, v_spacing=22)

        self.scroll_area.setWidget(self.grid_container)
        main_layout.addWidget(self.scroll_area)

        # 4. Empty State Widget
        self.empty_widget = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(12)

        self.empty_icon = QLabel(self.empty_widget)
        self.empty_icon.setPixmap(pixmap("library", size=72))
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_icon)

        self.empty_title = QLabel("No Series Found", self.empty_widget)
        font_title = QFont(self.font())
        font_title.setPointSize(18)
        font_title.setBold(True)
        self.empty_title.setFont(font_title)
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)

        self.empty_subtitle = QLabel("Add a root folder in Settings or scan your library to get started.", self.empty_widget)
        self.empty_subtitle.setStyleSheet(f"color: {color('text_muted')}; font-size: 13px;")
        self.empty_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_subtitle)

        self.empty_action_btn = QPushButton("Open Settings", self.empty_widget)
        self.empty_action_btn.setObjectName("primaryBtn")
        self.empty_action_btn.setIcon(icon("gear", size=16, color="#0A0A0A"))
        self.empty_action_btn.setIconSize(QSize(16, 16))
        self.empty_action_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.empty_action_btn.clicked.connect(self.open_settings_requested.emit)
        empty_layout.addWidget(self.empty_action_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(self.empty_widget)
        self.empty_widget.setVisible(False)

    def _toggle_show_hidden(self) -> None:
        self.show_hidden = self.show_hidden_btn.isChecked()
        self.show_hidden_btn.setProperty("active", "true" if self.show_hidden else "false")
        self.show_hidden_btn.style().unpolish(self.show_hidden_btn)
        self.show_hidden_btn.style().polish(self.show_hidden_btn)
        self.refresh()

    def refresh_icons(self) -> None:
        """Re-render icons after a theme change."""
        self.show_hidden_btn.setIcon(icon("eye" if self.show_hidden else "eye-off", size=16))
        self.empty_icon.setPixmap(pixmap("library", size=72))
        self.empty_action_btn.setIcon(icon("gear", size=16, color="#0A0A0A"))
        if self.carousel:
            self.carousel.refresh_icons()
        # Rebuild the grid so poster/badge icons pick up the new theme colour.
        self.refresh()

    def refresh(self) -> None:
        """Reload all series and refresh the grid view."""
        self.show_hidden_btn.setIcon(icon("eye" if self.show_hidden else "eye-off", size=16))
        # 1. Update Recently Watched Carousel if enabled
        if self.carousel:
            show_carousel = self.db.get_setting("show_recently_watched", "true").lower() == "true"
            if show_carousel:
                recents = self.db.get_recently_watched_episodes(limit=8)
                self.carousel.set_items(recents)
            else:
                self.carousel.setVisible(False)

        # 2. Update Tag Pills & Hidden Button status
        all_hidden = [s for s in self.db.get_all_series(include_hidden=True) if s.get("is_hidden")]
        hidden_count = len(all_hidden)
        if hidden_count > 0:
            self.show_hidden_btn.setVisible(True)
            self.show_hidden_btn.setText(f"Hidden ({hidden_count})")
        else:
            self.show_hidden_btn.setVisible(self.show_hidden)
            self.show_hidden_btn.setText("Hidden")

        self._refresh_tags(hidden_count)

        # 3. Load Series from Database
        include_hidden = self.show_hidden or (self.current_tag.lower() == "hidden")
        tag_filter = None if self.current_tag.lower() in ("all", "hidden") else self.current_tag
        series_list = self.db.get_all_series(
            include_hidden=include_hidden,
            only_favorites=self.only_favorites,
            tag=tag_filter,
            search_query=self.search_query,
            sort_by=self.current_sort
        )

        if self.current_tag.lower() == "hidden":
            series_list = [s for s in series_list if s.get("is_hidden")]
        elif not self.show_hidden:
            series_list = [s for s in series_list if not s.get("is_hidden")]

        # 4. Render Grid Cards
        self._render_grid(series_list)

    def set_search_query(self, query: str) -> None:
        """Update live search query and filter grid."""
        self.search_query = query.strip()
        self.refresh()

    def _refresh_tags(self, hidden_count: int = 0) -> None:
        """Rebuild tag filter chips."""
        while self.tags_layout.count() > 1:
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        all_tags = ["All"] + self.db.get_all_tags()
        if hidden_count > 0 and "Hidden" not in all_tags:
            all_tags.append("Hidden")

        for t in all_tags:
            label = f"Hidden ({hidden_count})" if t == "Hidden" else t
            btn = QPushButton(label, self.tags_container)
            btn.setObjectName("tagPill")
            btn.setProperty("active", "true" if t.lower() == self.current_tag.lower() else "false")
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda checked, tag_name=t: self._on_tag_selected(tag_name))
            self.tags_layout.insertWidget(self.tags_layout.count() - 1, btn)

    def _on_tag_selected(self, tag_name: str) -> None:
        self.current_tag = tag_name
        self.refresh()

    def _on_sort_changed(self, index: int) -> None:
        self.current_sort = self.sort_combo.currentData()
        self.refresh()

    def _render_grid(self, series_list: List[Dict[str, Any]]) -> None:
        # Clear existing cards safely
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item:
                w = item.widget()
                if w:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
        self._cards.clear()

        if not series_list:
            self.scroll_area.setVisible(False)
            self.empty_widget.setVisible(True)

            if self.search_query:
                self.empty_title.setText(f"No results for '{self.search_query}'")
                self.empty_subtitle.setText("Try searching for another title or clear the search filter.")
                self.empty_action_btn.setVisible(False)
            elif self.only_favorites:
                self.empty_title.setText("No Favorites Yet")
                self.empty_subtitle.setText("Right-click any series card or click the heart button to add it to favorites.")
                self.empty_action_btn.setVisible(False)
            elif self.current_tag.lower() == "hidden":
                self.empty_title.setText("No Hidden Items")
                self.empty_subtitle.setText("No series are currently marked as hidden.")
                self.empty_action_btn.setVisible(False)
            else:
                self.empty_title.setText("Your Library is Empty")
                self.empty_subtitle.setText("Add a root folder in Settings or scan your library to get started.")
                self.empty_action_btn.setVisible(True)
            return

        self.empty_widget.setVisible(False)
        self.scroll_area.setVisible(True)

        for s_data in series_list:
            card = SeriesCard(s_data, self.grid_container)
            card.clicked.connect(self.series_selected.emit)
            card.favorite_toggled.connect(self._toggle_card_favorite)
            card.customize_requested.connect(self._customize_series)
            card.hide_requested.connect(self._hide_series)
            card.unhide_requested.connect(self._unhide_series)
            card.play_next_requested.connect(self._play_next_series_episode)
            card.mark_all_watched.connect(self._mark_series_watched)
            card.remove_requested.connect(self._remove_series)

            self.grid_layout.addWidget(card)
            card.show()
            self._cards.append(card)

        self.grid_container.adjustSize()

    def _unhide_series(self, series_id: int) -> None:
        self.db.set_series_hidden(series_id, False)
        self.refresh()
        ToastNotification.show_toast(self.window(), "Series unhidden and restored to library grid.")

    def _toggle_card_favorite(self, series_id: int, new_fav_state: bool) -> None:
        self.db.set_series_favorite(series_id, new_fav_state)
        self.refresh()
        status = "Added to Favorites" if new_fav_state else "Removed from Favorites"
        ToastNotification.show_toast(self.window(), status)

    def _customize_series(self, series_id: int) -> None:
        modal = CustomizationModal(series_id, self.db, self)
        modal.customization_saved.connect(lambda _: self.refresh())
        modal.exec()

    def _hide_series(self, series_id: int) -> None:
        self.db.set_series_hidden(series_id, True)
        self.refresh()
        ToastNotification.show_toast(self.window(), "Series hidden. You can unhide it in Settings.")

    def _play_next_series_episode(self, series_id: int) -> None:
        episodes = self.db.get_episodes_for_series(series_id)
        if not episodes:
            series = self.db.get_series_by_id(series_id)
            if series and (series.get("source_type") or "local").lower() != "local":
                page_url = series.get("source_url") or ""
                if page_url:
                    open_url(page_url)
                    return
            ToastNotification.show_toast(self.window(), "No episodes found for this series.")
            return
        target = next((e for e in episodes if not e.get("watched")), episodes[0])
        success, err = self.media_player.play_episode(target["id"], resume=True)
        if not success:
            ToastNotification.show_toast(self.window(), f"Player Error: {err}")
        else:
            self.refresh()

    def _mark_series_watched(self, series_id: int, watched: bool) -> None:
        self.db.mark_all_episodes_watched(series_id, watched)
        self.refresh()
        ToastNotification.show_toast(
            self.window(),
            "All episodes marked as watched." if watched else "All episodes marked as unwatched."
        )

    def _resume_episode(self, episode_id: int) -> None:
        success, err = self.media_player.play_episode(episode_id, resume=True)
        if not success:
            ToastNotification.show_toast(self.window(), f"Player Error: {err}")
        else:
            self.refresh()

    def _remove_from_history(self, episode_id: int) -> None:
        """Remove a single episode from the Continue Watching strip."""
        self.db.remove_episode_from_history(episode_id)
        self.refresh()
        ToastNotification.show_toast(self.window(), "Removed from Continue Watching.")

    def _remove_series(self, series_id: int) -> None:
        """Delete an imported streaming show from the library.

        Only streaming sources can be removed this way - local folders are the
        scanner's territory and would simply reappear on the next scan.
        """
        series = self.db.get_series_by_id(series_id)
        if not series:
            return
        if (series.get("source_type") or "local").lower() == "local":
            ToastNotification.show_toast(
                self.window(), "Local series are managed by the scanner and cannot be removed here."
            )
            return

        title = series.get("display_title") or "this show"
        answer = QMessageBox.question(
            self.window(),
            "Remove from Library",
            f"Remove '{title}' from your library?\n\n"
            "This only removes it from Nook - the streaming site itself is untouched.\n"
            "You can add it again from the Browse tab.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.db.delete_series(series_id)
        self.refresh()
        ToastNotification.show_toast(self.window(), f"Removed '{title}' from your library.")
